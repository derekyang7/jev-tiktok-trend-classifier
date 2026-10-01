"""Domain models for the UGC version (UGC spec §6, §8)."""

from typing import Literal

FACETS = ("format", "hook", "sound", "topic", "need")
LLM_FACETS = ("format", "hook", "topic", "need")  # proposed by the LLM and assigned by Jev; sounds match by id
Facet = Literal["format", "hook", "sound", "topic", "need"]
BusinessUse = Literal["approved", "organic_only", "unknown"]
