"""Candidate ladder registry (spec 03 section 2). F, D and G are not implemented: the planner always
excludes them with a reason (no span tasks; no time budget for encoder fine-tuning; G is STRETCH, cut)."""
from backend.candidates.base import Candidate, Context
from backend.candidates.cascade_h import CascadeH
from backend.candidates.embed_i import EmbedClfB, EmbedClfC, EmbedKnnI
from backend.candidates.gbm_e import GbmE
from backend.candidates.prompted_k import PromptedK, PromptedL
from backend.candidates.rules_j import RulesJ
from backend.candidates.tfidf_a import TfidfA

FAMILIES: dict[str, type[Candidate]] = {
    "J": RulesJ, "A": TfidfA, "E": GbmE, "I": EmbedKnnI, "B": EmbedClfB, "C": EmbedClfC,
    "K": PromptedK, "L": PromptedL,
}
RUNG = {"J": 1, "A": 1, "E": 1, "F": 1, "I": 2, "B": 2, "C": 2, "D": 2, "K": 3, "L": 3, "G": 4, "H": 0}
LLM_FAMILIES = {"K", "L"}


def build(family: str, params: dict, ctx: Context) -> Candidate:
    return FAMILIES[family](params, ctx)


__all__ = ["Candidate", "Context", "CascadeH", "FAMILIES", "RUNG", "LLM_FAMILIES", "build"]
