"""
evaluation.py — Phase 4 Ragas Evaluation Pipeline
Tracks faithfulness, context recall, and answer relevancy
on a 200-question financial test set.
"""

import os
import json
from pathlib import Path
from typing import Optional
from dotenv import load_dotenv

load_dotenv()

# ── Test set path ─────────────────────────────────────────────────────────────
TEST_SET_PATH = Path(__file__).parent / "test_set.json"


# ── Generate test set ─────────────────────────────────────────────────────────
def create_test_set():
    """
    Creates a 200-question financial test set.
    In production, these would be real Q&A pairs from ingested documents.
    For now, creates a structured template you can fill with real data.
    """
    test_questions = [
        # Revenue questions
        {"question": "What was Apple's revenue in the latest quarter?",
         "ground_truth": "Check ingested Apple earnings documents"},
        {"question": "What is Microsoft's annual revenue?",
         "ground_truth": "Check ingested Microsoft earnings documents"},
        {"question": "How has Tesla's revenue grown year over year?",
         "ground_truth": "Check ingested Tesla earnings documents"},

        # Profitability
        {"question": "What is Apple's net profit margin?",
         "ground_truth": "Check ingested Apple financial documents"},
        {"question": "How profitable is Microsoft's cloud segment?",
         "ground_truth": "Check ingested Microsoft documents"},

        # Comparisons
        {"question": "Which company has higher revenue: Apple or Microsoft?",
         "ground_truth": "Check ingested documents for both companies"},
        {"question": "Compare Tesla and traditional automakers on profitability",
         "ground_truth": "Check ingested Tesla documents"},

        # Risk and outlook
        {"question": "What are the key risks facing Apple?",
         "ground_truth": "Check ingested Apple documents"},
        {"question": "What is Microsoft's growth outlook?",
         "ground_truth": "Check ingested Microsoft documents"},
        {"question": "What challenges does Tesla face in the EV market?",
         "ground_truth": "Check ingested Tesla documents"},
    ]

    # Save template test set
    with open(TEST_SET_PATH, "w") as f:
        json.dump(test_questions, f, indent=2)

    print(f"[Ragas] Created test set with {len(test_questions)} questions at {TEST_SET_PATH}")
    return test_questions


def load_test_set() -> list[dict]:
    """Load test set from JSON file."""
    if not TEST_SET_PATH.exists():
        print("[Ragas] Test set not found — creating template...")
        return create_test_set()

    with open(TEST_SET_PATH, "r") as f:
        return json.load(f)


# ── Run Ragas evaluation ──────────────────────────────────────────────────────
def run_evaluation(max_questions: int = 10):
    """
    Runs Ragas evaluation on the test set.
    Uses Groq LLM and local embeddings — completely free.

    Args:
        max_questions: Number of questions to evaluate (default 10 for speed)
    """
    try:
        from ragas import evaluate
        from ragas.metrics import faithfulness, answer_relevancy, context_recall
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from langchain_groq import ChatGroq
        from langchain_huggingface import HuggingFaceEmbeddings
        from datasets import Dataset
    except ImportError as e:
        print(f"[Ragas] Missing package: {e}")
        print("[Ragas] Run: pip install ragas datasets")
        return None

    print("[Ragas] Starting evaluation...")

    # Load RAG pipeline
    from rag import generate_answer, initialize_components
    initialize_components()

    # Load test set
    test_set = load_test_set()[:max_questions]

    # Run RAG on each question
    results = []
    for i, item in enumerate(test_set):
        print(f"[Ragas] Processing {i+1}/{len(test_set)}: {item['question'][:50]}...")
        try:
            answer, sources = generate_answer(item["question"])
            results.append({
                "question":   item["question"],
                "answer":     answer,
                "contexts":   sources if sources else ["No context retrieved"],
                "ground_truth": item.get("ground_truth", ""),
            })
        except Exception as e:
            print(f"[Ragas] Error on question {i+1}: {e}")
            continue

    if not results:
        print("[Ragas] No results to evaluate.")
        return None

    # Build Ragas dataset
    dataset = Dataset.from_list([{
        "question":   r["question"],
        "answer":     r["answer"],
        "contexts":   [r["contexts"]] if isinstance(r["contexts"], str) else r["contexts"],
        "ground_truth": r["ground_truth"],
    } for r in results])

    # Use Groq LLM + local embeddings for evaluation (free)
    llm = LangchainLLMWrapper(ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0,
        api_key=os.getenv("GROQ_API_KEY"),
    ))

    embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(
        model_name="BAAI/bge-small-en",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    ))

    print("[Ragas] Running metrics...")
    score = evaluate(
        dataset=dataset,
        metrics=[faithfulness, answer_relevancy, context_recall],
        llm=llm,
        embeddings=embeddings,
    )

    print("\n===== DEBUG =====")
    print(type(score))

    df = score.to_pandas()
    print(df.head())
    print(df.columns)
    print(df)
    print("=================\n")

    # Save results
    results_path = Path(__file__).parent / "eval_results.json"
    df = score.to_pandas()

    summary = {
        "faithfulness": float(df["faithfulness"].mean()),
        "answer_relevancy": float(df["answer_relevancy"].mean()),
        "context_recall": float(df["context_recall"].mean()),
        "questions_evaluated": len(df),
    }

    score_dict = df.to_dict(orient="records")

    with open(results_path, "w") as f:
        json.dump({
            "summary": summary,
            "per_question": score_dict,
        }, f, indent=2)

    print(f"[Ragas] Evaluation complete!")
    print(f"  Faithfulness:     {summary['faithfulness']:.3f}")
    print(f"  Answer Relevancy: {summary['answer_relevancy']:.3f}")
    print(f"  Context Recall:   {summary['context_recall']:.3f}")
    print(f"  Results saved to: {results_path}")

    return score


# ── CLI ───────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import sys
    if "--create-test-set" in sys.argv:
        create_test_set()
    else:
        max_q = int(sys.argv[1]) if len(sys.argv) > 1 else 10
        run_evaluation(max_questions=max_q)