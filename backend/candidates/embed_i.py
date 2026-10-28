"""I, B, C: embedding families.

I: cosine similarity to labeled examples (kNN) or class centroids; no training. Local or cloud embeddings.
B: Qwen3-Embedding-8B (Token Factory) + logistic regression or a small MLP. Needs cloud_ok.
C: local MiniLM-class model + logistic regression or a small MLP. Offline at inference.
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.neural_network import MLPClassifier

from backend.candidates.base import Candidate, cloud_embed, local_embed, prep_text, softmax

LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class _Embedding(Candidate):
    rung = 2
    backend = "local"

    def _emb(self, texts):
        X = [prep_text(t, self.ctx.input_type)[:2000] for t in texts]
        if self.backend == "cloud":
            vecs, usage = cloud_embed(X, self.ctx.llm, use_cache=not self.bypass_cache)
            if usage.get("mean_tokens_per_text"):
                self._tokens = usage["mean_tokens_per_text"]
            return vecs
        return local_embed(X, self.params.get("local_model", LOCAL_MODEL), use_cache=not self.bypass_cache)

    def usage_stats(self):
        if self.backend != "cloud":
            return None
        return {"role": "embeddings", "mean_prompt_tokens": getattr(self, "_tokens", None),
                "mean_completion_tokens": 0.0}


class EmbedKnnI(_Embedding):
    family = "I"

    def __init__(self, params, ctx):
        super().__init__(params, ctx)
        self.backend = params.get("backend", "local")
        self.uses_cloud = self.backend == "cloud"

    def fit(self, texts, y, progress=None):
        self.E = self._emb(texts).astype(np.float32)
        self.y = self.y_index(y)
        self.train_texts = list(texts)
        if self.params.get("method", "knn") == "centroid":
            C = np.stack([self.E[self.y == k].mean(0) if (self.y == k).any() else np.zeros(self.E.shape[1])
                          for k in range(len(self.labels))])
            self.C = C / (np.linalg.norm(C, axis=1, keepdims=True) + 1e-9)
        if progress:
            progress({"step": 1, "examples": len(texts)})

    def predict_proba(self, texts):
        Q = self._emb(texts)
        temp = float(self.params.get("temperature", 0.05))
        if self.params.get("method", "knn") == "centroid":
            return softmax(Q @ self.C.T, temp)
        k = int(self.params.get("k", 10))
        S = Q @ self.E.T
        top = np.argpartition(-S, min(k, S.shape[1] - 1), axis=1)[:, :k]
        out = np.full((len(texts), len(self.labels)), 1e-6)
        for i in range(len(texts)):
            w = np.exp(S[i, top[i]] / temp)
            np.add.at(out[i], self.y[top[i]], w)
        return out / out.sum(axis=1, keepdims=True)

    def reason(self, text, proba):
        q = self._emb([text])[0]
        j = int(np.argmax(self.E @ q))
        ex = self.train_texts[j]
        ex = ex if len(ex) < 90 else ex[:87] + "…"
        return f"Most similar labeled example: \"{ex}\" ({self.labels[self.y[j]]})."

    def attach(self, llm):
        self.uses_cloud = self.backend == "cloud"


def strip_mlp_training_state(clf) -> None:
    """Drop what an MLP only needs to keep training (Adam moments, the early-stopping copy of the weights).
    Prediction uses coefs_ / intercepts_ only; this roughly halves the bundle."""
    for attr in ("_optimizer", "_best_coefs", "_best_intercepts"):
        if hasattr(clf, attr):
            delattr(clf, attr)


class _EmbedClassifier(_Embedding):
    def fit(self, texts, y, progress=None):
        E = self._emb(texts)
        if progress:
            progress({"step": 1, "embedded": len(texts)})
        yi = self.y_index(y)
        if self.params.get("head", "logreg") == "mlp":
            # One hidden layer; early stopping holds out 10% of the training rows (never validation).
            self.clf = MLPClassifier(hidden_layer_sizes=(int(self.params.get("hidden", 256)),),
                                     alpha=float(self.params.get("alpha", 1e-4)), early_stopping=True,
                                     max_iter=300, random_state=self.ctx.seed)
        else:
            self.clf = LogisticRegression(C=float(self.params.get("C", 4.0)), max_iter=3000,
                                          class_weight="balanced" if self.params.get("class_weight_balanced", True) else None,
                                          random_state=self.ctx.seed)
        self.clf.fit(E, yi)
        strip_mlp_training_state(self.clf)
        if progress:
            progress({"step": 2})

    def predict_proba(self, texts):
        return self.full_proba(self.clf.predict_proba(self._emb(texts)), self.clf.classes_)


class EmbedClfB(_EmbedClassifier):
    family, backend, uses_cloud = "B", "cloud", True


class EmbedClfC(_EmbedClassifier):
    family, backend = "C", "local"
