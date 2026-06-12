"""
Add this router to main.py for Phase 4 evaluation endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from auth import require_admin

router = APIRouter(prefix="/eval", tags=["Evaluation"])


@router.post("/run")
async def run_evaluation(
    background_tasks: BackgroundTasks,
    max_questions: int = 10,
    user: dict = Depends(require_admin)
):
    """
    Admin only — runs Ragas evaluation in background.
    Results saved to eval_results.json
    """
    def _run():
        from evaluation import run_evaluation
        run_evaluation(max_questions=max_questions)

    background_tasks.add_task(_run)
    return {
        "message": f"Evaluation started for {max_questions} questions",
        "status": "running in background"
    }


@router.get("/results")
def get_eval_results(user: dict = Depends(require_admin)):
    """Admin only — returns latest Ragas evaluation results."""
    import json
    from pathlib import Path

    results_path = Path(__file__).parent / "eval_results.json"
    if not results_path.exists():
        raise HTTPException(
            status_code=404,
            detail="No evaluation results found. Run POST /eval/run first."
        )

    with open(results_path, "r") as f:
        return json.load(f)