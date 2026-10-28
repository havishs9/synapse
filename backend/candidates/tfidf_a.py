"""A: TF-IDF (word + char n-grams) with logistic regression or a linear SVM."""
from __future__ import annotations

import numpy as np
from scipy.sparse import hstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.svm import LinearSVC

from backend.candidates.base import Candidate, prep_text, softmax


class TfidfA(Candidate):
    family, rung = "A", 1

    def fit(self, texts, y, progress=None):
        p = self.params
        X = [prep_text(t, self.ctx.input_type) for t in texts]
        self.word = TfidfVectorizer(ngram_range=(1, int(p.get("word_ngram_max", 2))), min_df=2, sublinear_tf=True,
                                    max_features=int(p.get("max_features", 50000)))
        mats = [self.word.fit_transform(X)]
        self.char = None
        if p.get("char", True):
            self.char = TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=3, sublinear_tf=True,
                                        max_features=int(p.get("max_features", 50000)))
            mats.append(self.char.fit_transform(X))
        Xm = hstack(mats).tocsr()
        cw = "balanced" if p.get("class_weight_balanced", True) else None
        if p.get("model", "logreg") == "svm":
            self.clf = LinearSVC(C=float(p.get("C", 1.0)), class_weight=cw, random_state=self.ctx.seed)
        else:
            self.clf = LogisticRegression(C=float(p.get("C", 4.0)), max_iter=2000, class_weight=cw,
                                          random_state=self.ctx.seed)
        if progress:
            progress({"step": 1, "features": Xm.shape[1]})
        self.clf.fit(Xm, self.y_index(y))
        if progress:
            progress({"step": 2})

    def _X(self, texts):
        X = [prep_text(t, self.ctx.input_type) for t in texts]
        mats = [self.word.transform(X)] + ([self.char.transform(X)] if self.char is not None else [])
        return hstack(mats).tocsr()

    def predict_proba(self, texts):
        Xm = self._X(texts)
        if hasattr(self.clf, "predict_proba"):
            return self.full_proba(self.clf.predict_proba(Xm), self.clf.classes_)
        z = self.clf.decision_function(Xm)
        if z.ndim == 1:
            z = np.stack([-z, z], axis=1)
        return self.full_proba(softmax(z, 0.3), self.clf.classes_)

    def reason(self, text, proba):
        k = int(np.argmax(proba))
        ci = list(self.clf.classes_).index(k) if k in self.clf.classes_ else None
        if ci is None:
            return None
        x = self._X([text])
        coef = self.clf.coef_[ci] if self.clf.coef_.shape[0] > 1 else self.clf.coef_[0] * (1 if ci == 1 else -1)
        contrib = x.multiply(coef).tocsr()
        names = list(self.word.get_feature_names_out()) + (list(self.char.get_feature_names_out()) if self.char is not None else [])
        top = sorted(zip(contrib.data, contrib.indices), reverse=True)[:3]
        terms = [names[j].strip() for v, j in top if v > 0]
        return f"Words that point to {self.labels[k]}: " + ", ".join(f"\"{t}\"" for t in terms) if terms else None
