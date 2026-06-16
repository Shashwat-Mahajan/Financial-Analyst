"""
evaluation.py — Phase 4 Ragas Evaluation Pipeline
Fixed: Updated Ragas 0.4.x API, rate limit handling
"""

import os
import json
import time
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

TEST_SET_PATH = Path(__file__).parent / "test_set.json"


def load_test_set() -> list[dict]:
    if not TEST_SET_PATH.exists():
        raise FileNotFoundError(f"Test set not found at {TEST_SET_PATH}")
    with open(TEST_SET_PATH, "r") as f:
        return json.load(f)


def run_evaluation(max_questions: int = 5):
    try:
        from ragas import evaluate
        from ragas.metrics import Faithfulness, AnswerRelevancy, ContextRecall
        from ragas.llms import LangchainLLMWrapper
        from ragas.embeddings import LangchainEmbeddingsWrapper
        from langchain_groq import ChatGroq
        from langchain_huggingface import HuggingFaceEmbeddings
        from datasets import Dataset
    except ImportError as e:
        print(f"[Ragas] Missing package: {e}")
        return None

    print("[Ragas] Starting evaluation...")

    from rag import generate_answer, initialize_components
    initialize_components()

    test_set = load_test_set()[:max_questions]
    results  = []

    for i, item in enumerate(test_set):
        print(f"[Ragas] Processing {i+1}/{len(test_set)}: {item['question'][:50]}...")
        try:
            answer, sources = generate_answer(item["question"])
            results.append({
                "question":     item["question"],
                "answer":       answer,
                "contexts":     sources if sources else ["No context retrieved"],
                "ground_truth": item.get("ground_truth", ""),
            })
            time.sleep(3)  # avoid rate limits between questions
        except Exception as e:
            print(f"[Ragas] Skipping question {i+1} due to error: {e}")
            continue

    if not results:
        print("[Ragas] No results to evaluate — all questions failed.")
        return None

    print(f"[Ragas] Successfully processed {len(results)}/{len(test_set)} questions.")

    dataset = Dataset.from_list([{
        "user_input":         r["question"],
        "response":           r["answer"],
        "retrieved_contexts": r["contexts"] if isinstance(r["contexts"], list) else [r["contexts"]],
        "reference":          r["ground_truth"],
    } for r in results])

    # Initialize LLM and embeddings
    llm = LangchainLLMWrapper(ChatGroq(
        model="llama-3.3-70b-versatile",
        temperature=0,
        max_tokens=500,
        api_key=os.getenv("GROQ_API_KEY"),
    ))

    embeddings = LangchainEmbeddingsWrapper(HuggingFaceEmbeddings(
        model_name="BAAI/bge-small-en",
        model_kwargs={"device": "cpu"},
        encode_kwargs={"normalize_embeddings": True},
    ))

    # Initialize metric objects (Ragas 0.4.x requires instantiated objects)
    faithfulness    = Faithfulness(llm=llm)
    answer_relevancy = AnswerRelevancy(llm=llm, embeddings=embeddings)
    context_recall  = ContextRecall(llm=llm)

    print("[Ragas] Running metrics...")
    try:
        score = evaluate(
            dataset=dataset,
            metrics=[faithfulness, answer_relevancy, context_recall],
            raise_exceptions=False,
        )
    except Exception as e:
        print(f"[Ragas] Evaluation error: {e}")
        return None

    # Save results
    results_path = Path(__file__).parent / "eval_results.json"
    try:
        df      = score.to_pandas()
        summary = {
            "faithfulness":        round(float(df["faithfulness"].mean(skipna=True)), 3),
            "answer_relevancy":    round(float(df["answer_relevancy"].mean(skipna=True)), 3),
            "context_recall":      round(float(df["context_recall"].mean(skipna=True)), 3),
            "questions_evaluated": len(results),
        }
        with open(results_path, "w") as f:
            json.dump({
                "summary":      summary,
                "per_question": df.fillna(0).to_dict(orient="records"),
            }, f, indent=2)

        print(f"\n[Ragas] Evaluation complete!")
        print(f"  Faithfulness:     {summary['faithfulness']}")
        print(f"  Answer Relevancy: {summary['answer_relevancy']}")
        print(f"  Context Recall:   {summary['context_recall']}")
        print(f"  Results saved to: {results_path}")
        return score

    except Exception as e:
        print(f"[Ragas] Error saving results: {e}")
        return score


if __name__ == "__main__":
    import sys
    max_q = int(sys.argv[1]) if len(sys.argv) > 1 else 5
    run_evaluation(max_questions=max_q)