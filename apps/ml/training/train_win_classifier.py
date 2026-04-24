"""Offline training script — win probability classifier.

Builds a simple logistic-regression baseline over historical proposals. Tracks runs
to MLflow so experiments are comparable. Run after a representative dataset exists:

    python -m training.train_win_classifier --org-id <uuid> --out models/win_clf.pkl
"""
from __future__ import annotations

import argparse
import logging
import os
import pickle
from dataclasses import dataclass

import mlflow
import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, roc_auc_score
from sklearn.model_selection import train_test_split
from sqlalchemy import create_engine, text

log = logging.getLogger(__name__)


@dataclass
class TrainingRow:
    area_sqm: float
    floors: int
    total_fee_vnd: int
    ai_confidence: float
    project_type: str
    won: int


FEATURE_COLUMNS = ["area_sqm", "floors", "total_fee_vnd", "ai_confidence"]


def load_dataset(database_url: str, organization_id: str) -> list[TrainingRow]:
    engine = create_engine(database_url)
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                """
                SELECT
                    COALESCE(pr.area_sqm, 0) AS area_sqm,
                    COALESCE(pr.floors, 0)   AS floors,
                    COALESCE(p.total_fee_vnd, 0) AS total_fee_vnd,
                    COALESCE(p.ai_confidence, 0) AS ai_confidence,
                    COALESCE(pr.type, 'unknown') AS project_type,
                    CASE WHEN p.status = 'won' THEN 1 ELSE 0 END AS won
                FROM proposals p
                LEFT JOIN projects pr ON pr.id = p.project_id
                WHERE p.organization_id = :org
                  AND p.status IN ('won', 'lost')
                """
            ),
            {"org": organization_id},
        ).all()
    return [TrainingRow(**dict(r._mapping)) for r in rows]


def to_matrix(rows: list[TrainingRow]) -> tuple[np.ndarray, np.ndarray]:
    x = np.array([[r.area_sqm, r.floors, r.total_fee_vnd, r.ai_confidence] for r in rows], dtype=float)
    y = np.array([r.won for r in rows], dtype=int)
    return x, y


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--org-id", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    database_url = os.environ["DATABASE_URL_SYNC"]
    rows = load_dataset(database_url, args.org_id)
    if len(rows) < 20:
        raise SystemExit(f"Not enough training data: {len(rows)} rows (need >= 20)")

    x, y = to_matrix(rows)
    x_train, x_test, y_train, y_test = train_test_split(x, y, test_size=0.2, random_state=42, stratify=y)

    mlflow.set_experiment("winwork-win-probability")
    with mlflow.start_run():
        model = LogisticRegression(max_iter=500)
        model.fit(x_train, y_train)

        y_pred = model.predict(x_test)
        y_proba = model.predict_proba(x_test)[:, 1]

        mlflow.log_metric("accuracy", accuracy_score(y_test, y_pred))
        mlflow.log_metric("roc_auc", roc_auc_score(y_test, y_proba))
        mlflow.log_param("n_rows", len(rows))

        os.makedirs(os.path.dirname(args.out), exist_ok=True)
        with open(args.out, "wb") as fh:
            pickle.dump({"model": model, "features": FEATURE_COLUMNS}, fh)
        mlflow.log_artifact(args.out)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    main()
