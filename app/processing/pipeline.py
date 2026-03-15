import asyncio
import functools
import logging
from pathlib import Path

from app.config import Settings
from app.api.schemas import JobStatus
from app.jobs.manager import job_manager

logger = logging.getLogger(__name__)


async def _in_thread(func, *args, **kwargs):
    """Run a synchronous blocking call in the default thread-pool executor."""
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None, functools.partial(func, *args, **kwargs)
    )


async def run_pipeline(job_id: str, video_path: Path, settings: Settings):
    """Main pipeline orchestrator. Runs as a background task."""
    try:
        # Heavy imports inside try so any ImportError marks the job FAILED
        # instead of being silently swallowed by FastAPI BackgroundTasks.
        from app.agent.analyzer import analyze_video
        from app.agent.planner import generate_editing_plan
        from app.processing.opencv_engine import extract_video_metadata
        from app.processing.ffmpeg_engine import FFmpegEngine
        from app.processing.moviepy_engine import MoviePyEngine
        from app.processing.subtitle_engine import generate_srt, generate_ass

        work_dir = settings.temp_dir / job_id
        work_dir.mkdir(parents=True, exist_ok=True)

        # --- Phase 1: Upload raw to GCS (if configured) ---
        await job_manager.update_job(
            job_id, status=JobStatus.UPLOADING, progress=5,
            current_step="Uploading to cloud storage",
        )
        if settings.gcp_project_id:
            try:
                from app.storage.gcs import upload_to_gcs
                gcs_raw_path = f"raw/{job_id}/{video_path.name}"
                raw_uri = await upload_to_gcs(video_path, gcs_raw_path)
                await job_manager.update_job(job_id, raw_gcs_uri=raw_uri)
            except Exception as e:
                logger.warning(f"GCS upload skipped: {e}")
        await job_manager.update_job(job_id, progress=10)

        # --- Phase 2: Extract metadata ---
        await job_manager.update_job(
            job_id, status=JobStatus.ANALYZING, progress=15,
            current_step="Extracting video metadata",
        )
        metadata = await _in_thread(extract_video_metadata, video_path)
        logger.info(f"Video metadata: {metadata}")

        # --- Phase 3: AI Analysis ---
        await job_manager.update_job(
            job_id, progress=20,
            current_step="AI analyzing video content",
        )
        analysis = await analyze_video(video_path, settings)
        await job_manager.update_job(job_id, progress=40)

        # --- Phase 4: AI Planning ---
        await job_manager.update_job(
            job_id, status=JobStatus.PLANNING, progress=45,
            current_step="Generating editing plan",
        )
        plan = await generate_editing_plan(analysis, metadata, settings)
        await job_manager.update_job(
            job_id, editing_plan=plan.model_dump(), progress=55,
        )

        # --- Phase 5: Render ---
        await job_manager.update_job(
            job_id, status=JobStatus.RENDERING, progress=60,
            current_step="Rendering edited video",
        )

        ffmpeg = FFmpegEngine(video_path, work_dir, settings)
        moviepy = MoviePyEngine(work_dir)

        # 5a: Execute cuts
        await job_manager.update_job(job_id, progress=62, current_step="Cutting segments")
        segments = await _in_thread(ffmpeg.execute_cuts, plan.scenes)

        # 5b: Apply speed changes
        await job_manager.update_job(job_id, progress=67, current_step="Applying speed effects")
        segments = await _in_thread(ffmpeg.apply_speed_changes, segments, plan.scenes)

        # 5c: Concatenate segments with transitions
        await job_manager.update_job(job_id, progress=72, current_step="Joining scenes")
        base_video = await _in_thread(moviepy.concatenate_with_transitions, segments, plan.scenes)

        # 5d: Apply zoom effects
        await job_manager.update_job(job_id, progress=75, current_step="Applying zoom effects")
        base_video = await _in_thread(moviepy.apply_zoom_effects, base_video, plan.scenes)

        # 5e: Write intermediate — carry the correctly-timed audio through
        await job_manager.update_job(job_id, progress=78, current_step="Color grading")
        intermediate = work_dir / "intermediate.mp4"
        await _in_thread(
            base_video.write_videofile,
            str(intermediate),
            codec="libx264",
            preset="fast",
            audio_codec="aac",
            threads=2,
            ffmpeg_params=["-x264-params", "rc-lookahead=10:ref=1"],
        )
        base_video.close()

        # 5f: Apply color grading (skipped automatically if values are all neutral)
        graded_path = await _in_thread(ffmpeg.apply_color_grade, intermediate, plan.color_grade_global)

        # 5g: Generate subtitles
        await job_manager.update_job(job_id, progress=80, current_step="Generating subtitles")
        srt_path = await _in_thread(generate_srt, plan.subtitles, work_dir / "subtitles.srt")
        ass_path = await _in_thread(generate_ass, plan.subtitles, work_dir / "subtitles.ass")

        # 5h: Burn subtitles (skip if no subtitles to avoid empty-filter error)
        await job_manager.update_job(job_id, progress=82, current_step="Burning subtitles")
        if plan.subtitles:
            subtitled_path = work_dir / "subtitled.mp4"
            await _in_thread(ffmpeg.burn_subtitles, graded_path, ass_path, subtitled_path)
        else:
            subtitled_path = graded_path

        # 5i + 5j: Overlays and 16:9 output.
        # If no overlay actions exist, skip MoviePy entirely and use FFmpeg
        # for the resize — this avoids a second memory-heavy MoviePy pass.
        from app.agent.models import ActionType
        has_overlays = any(
            a.action_type in (ActionType.TYPOGRAPHY, ActionType.LOWER_THIRD)
            for s in plan.scenes for a in s.actions
        )

        await job_manager.update_job(job_id, progress=84, current_step="Adding overlays")
        output_16x9 = work_dir / "final_16x9.mp4"
        landscape_format = next(
            (f for f in plan.output_formats if f.aspect_ratio == "16:9"),
            plan.output_formats[0] if plan.output_formats else None,
        )

        if has_overlays and landscape_format:
            from moviepy import VideoFileClip
            subtitled_clip = VideoFileClip(str(subtitled_path))
            final_composed = await _in_thread(moviepy.apply_overlays, subtitled_clip, plan.scenes)

            await job_manager.update_job(job_id, progress=90, current_step="Rendering 16:9")
            await _in_thread(
                moviepy.render_final,
                final_composed,
                output_16x9,
                landscape_format,
            )
        elif landscape_format:
            await job_manager.update_job(job_id, progress=90, current_step="Rendering 16:9")
            target_w, target_h = landscape_format.resolution
            await _in_thread(ffmpeg.resize_video, subtitled_path, output_16x9, target_w, target_h)

        # 5k: Produce 9:16 output
        await job_manager.update_job(job_id, progress=95, current_step="Rendering 9:16")
        output_9x16 = work_dir / "final_9x16.mp4"
        vertical_format = next(
            (f for f in plan.output_formats if f.aspect_ratio == "9:16"), None,
        )
        if vertical_format and output_16x9.exists():
            await _in_thread(ffmpeg.crop_to_vertical, output_16x9, output_9x16, vertical_format)

        # --- Phase 6: Upload results (if GCS configured) ---
        await job_manager.update_job(job_id, current_step="Uploading results")
        output_uris = {}
        if settings.gcp_project_id:
            try:
                from app.storage.gcs import upload_to_gcs
                if output_16x9.exists():
                    gcs_16x9 = f"output/{job_id}/final_16x9.mp4"
                    output_uris["16:9"] = await upload_to_gcs(
                        output_16x9, gcs_16x9, "video/mp4",
                    )
                if output_9x16.exists():
                    gcs_9x16 = f"output/{job_id}/final_9x16.mp4"
                    output_uris["9:16"] = await upload_to_gcs(
                        output_9x16, gcs_9x16, "video/mp4",
                    )
            except Exception as e:
                logger.warning(f"GCS upload of results skipped: {e}")

        # If no GCS, store local paths as URIs for download endpoint
        if not output_uris:
            if output_16x9.exists():
                output_uris["16:9"] = str(output_16x9)
            if output_9x16.exists():
                output_uris["9:16"] = str(output_9x16)

        # --- Done ---
        await job_manager.update_job(
            job_id,
            status=JobStatus.COMPLETED,
            progress=100,
            current_step="Complete",
            output_gcs_uris=output_uris,
        )
        logger.info(f"Pipeline complete for job {job_id}")

    except Exception as e:
        logger.exception(f"Pipeline failed for job {job_id}: {e}")
        await job_manager.update_job(
            job_id,
            status=JobStatus.FAILED,
            error=str(e),
            current_step=f"Failed: {str(e)[:200]}",
        )
