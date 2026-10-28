"""E: LightGBM on engineered features (window features for logs; SVD of TF-IDF + length features for text)."""
from __future__ import annotations

import numpy as np

from backend.candidates.base import Candidate, prep_text


class GbmE(Candidate):
    family, rung = "E", 1

    def _parser(self):
        from backend.features.logs import TemplateParser
        if not hasattr(self, "_p"):
            self._p = TemplateParser(self.ctx.log_templates)
        return self._p

    def __getstate__(self):
        state = super().__getstate__()
        state.pop("_p", None)
        return state

    def _features(self, texts, fit=False):
        if self.ctx.input_type == "log_window":
            from backend.features.logs import window_features
            rows = [window_features(t, self._parser()) for t in texts]
            if fit:
                self.feature_names = sorted(rows[0])
            return np.array([[r[k] for k in self.feature_names] for r in rows], float), rows
        from sklearn.decomposition import TruncatedSVD
        from sklearn.feature_extraction.text import TfidfVectorizer
        X = [prep_text(t, self.ctx.input_type) for t in texts]
        if fit:
            self.tfidf = TfidfVectorizer(ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=30000)
            self.svd = TruncatedSVD(n_components=int(self.params.get("svd_dims", 100)), random_state=self.ctx.seed)
            Z = self.svd.fit_transform(self.tfidf.fit_transform(X))
            self.feature_names = [f"svd_{i}" for i in range(Z.shape[1])] + ["chars", "words", "digits"]
        else:
            Z = self.svd.transform(self.tfidf.transform(X))
        extra = np.array([[len(t), len(t.split()), sum(c.isdigit() for c in t)] for t in texts], float)
        return np.hstack([Z, extra]), None

    def fit(self, texts, y, progress=None):
        import lightgbm as lgb
        p = self.params
        X, rows = self._features(texts, fit=True)
        yi = self.y_index(y)
        self.clf = lgb.LGBMClassifier(
            n_estimators=int(p.get("n_estimators", 300)), learning_rate=float(p.get("learning_rate", 0.05)),
            num_leaves=int(p.get("num_leaves", 31)), min_child_samples=int(p.get("min_child_samples", 10)),
            class_weight="balanced" if p.get("class_weight_balanced", True) else None,
            subsample=0.9, subsample_freq=1, colsample_bytree=0.9, random_state=self.ctx.seed, verbose=-1, n_jobs=1)
        cb = []
        if progress:
            def _cb(env):
                if env.iteration % 50 == 0:
                    progress({"step": env.iteration})
            cb = [_cb]
        self.clf.fit(X, yi, callbacks=cb)
        if self.ctx.input_type == "log_window":
            imp = self.clf.booster_.feature_importance("gain")
            self.importances = dict(zip(self.feature_names, (imp / max(imp.sum(), 1e-9)).tolist()))
            neg = [r for r, lab in zip(rows, y) if lab != self.ctx.positive]
            self.baseline = {k: float(np.mean([r[k] for r in neg])) for k in self.feature_names} if neg else {}

    def predict_proba(self, texts):
        X, _ = self._features(texts)
        return self.full_proba(self.clf.predict_proba(X), self.clf.classes_)

    def reason(self, text, proba):
        if self.ctx.input_type != "log_window":
            return None
        from backend.features.logs import feature_reason, window_features
        feats = window_features(text, self._parser())
        return feature_reason(feats, self.importances, self._parser(), self.baseline)
