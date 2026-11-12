"""pipeline/to_engine.py's accent-insensitive player-name matching, found missing live
(friend playtesting the real deployment): searching "Odegaard" or "Gyokeres" returned
nothing because the stored names are "Ødegaard"/"Gyökeres", and searching "Vinícius"
(with the accent) also returned nothing because the stored name is "Vinicius Junior"
(without one). Both directions must work -- the user doesn't know which way a given
name happens to be stored.
"""

from __future__ import annotations

from pipeline.to_engine import _match_rank, normalize_name


def test_letters_with_no_combining_mark_decomposition_fold_to_ascii() -> None:
    # NFKD alone doesn't reduce these -- they need the explicit translation table.
    assert normalize_name("Ødegaard") == normalize_name("Odegaard")
    assert normalize_name("Gyökeres") == normalize_name("Gyokeres")
    assert normalize_name("İlkay") == normalize_name("Ilkay")
    assert normalize_name("Müller") == normalize_name("Muller")


def test_matching_works_in_both_directions() -> None:
    # The accent can be on either the stored name or the search text -- "Vinícius"
    # (accented search) must still find the stored "Vinicius Junior" (unaccented).
    assert normalize_name("Vinicius") in normalize_name("Vinícius Junior")
    assert normalize_name("Vinícius") in normalize_name("Vinicius Junior")


def test_case_insensitive_too() -> None:
    assert normalize_name("ODEGAARD") == normalize_name("odegaard")


def test_match_rank_prefers_exact_then_prefix_then_contains() -> None:
    q = normalize_name("Rodri")
    assert _match_rank(normalize_name("Rodri"), q) == 0
    assert _match_rank(normalize_name("Rodrigo"), q) == 1
    assert _match_rank(normalize_name("Rodrigo Zalazar"), q) == 1
    assert _match_rank(normalize_name("Takuma Rodriguez"), q) == 2
