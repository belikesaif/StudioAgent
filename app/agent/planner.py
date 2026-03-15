import json
import logging

from google.genai import types

from app.agent.client import get_genai_client
from app.agent.prompts import PLANNING_PROMPT
from app.agent.models import EditingPlan
from app.config import Settings

logger = logging.getLogger(__name__)


async def generate_editing_plan(
    analysis: dict,
    video_metadata: dict,
    settings: Settings,
) -> EditingPlan:
    """
    Given video analysis, generate a structured editing plan via Gemini.
    Returns a validated EditingPlan Pydantic model.
    """
    client = get_genai_client()

    # Inject video metadata into analysis for the planner
    analysis["video_metadata"] = video_metadata

    # Format the planning prompt with analysis data
    prompt = PLANNING_PROMPT.format(analysis_json=json.dumps(analysis, indent=2))

    # Call Gemini with structured output schema
    response = client.models.generate_content(
        model=settings.gemini_model,
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=EditingPlan,
            temperature=0.4,
        ),
    )

    # Parse and validate against Pydantic model
    plan_data = json.loads(response.text)
    plan = EditingPlan.model_validate(plan_data)

    logger.info(
        f"Editing plan generated: {len(plan.scenes)} scenes, "
        f"{len(plan.subtitles)} subtitles, "
        f"{sum(len(s.actions) for s in plan.scenes)} actions"
    )

    return plan
