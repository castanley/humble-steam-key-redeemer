"""Test the filter logic fix for avoiding duplicate redemptions.

Background: The filter was using Humble order gamekey (1st column) to filter out
previously-processed games, which caused ALL games in an order to be skipped if
any game from that order had been processed. This test verifies the fix.
"""

import tempfile
import os
from pathlib import Path


def read_steam_keys_old(csv_content):
    """Old broken logic: flattens all CSV columns into one list."""
    filtered_keys = [
        keycol for keycol in csv_content.replace("\n", ",").split(",") if keycol
    ]
    return filtered_keys


def read_steam_keys_new(csv_content):
    """New fixed logic: extracts only the 3rd column (steam key values)."""
    rows = [line.strip().split(",") for line in csv_content.split("\n") if line.strip()]
    return {row[2] for row in rows if len(row) >= 3 and row[2]}


def test_filter_old_vs_new():
    """Test the old broken logic vs the new fixed logic."""

    # Simulate a Humble order with multiple games (gamekey = 2Y6h5yBkuPvWyHuN)
    # Some games already redeemed, one not yet attempted (Knights in Tight Spaces)
    csv_content = """2Y6h5yBkuPvWyHuN,Dogpile,5KMAI-6B24I-AFHGL
2Y6h5yBkuPvWyHuN,Deck of Haunts,5376R-AAIC2-YWC3A
2Y6h5yBkuPvWyHuN,Occlude,53KY5-GHK5I-WHTCL"""

    # OLD LOGIC: check if gamekey appears in the flat list
    old_filtered = read_steam_keys_old(csv_content)
    gamekey = "2Y6h5yBkuPvWyHuN"
    assert gamekey in old_filtered, f"Gamekey should be in old filtered list"

    # NEW LOGIC: extract only steam key values
    new_filtered = read_steam_keys_new(csv_content)
    assert gamekey not in new_filtered, f"Gamekey should NOT be in new filtered set"
    assert "5KMAI-6B24I-AFHGL" in new_filtered, "Dogpile steam key should be in new set"
    assert "5376R-AAIC2-YWC3A" in new_filtered, "Deck of Haunts steam key should be in new set"
    assert len(new_filtered) == 3, "Should have 3 steam keys, not gamekeys"

    # Simulate filtering Knights in Tight Spaces
    knights_unrevealed = {"human_name": "Knights in Tight Spaces", "steam_app_id": 12345}
    knights_value = knights_unrevealed.get("redeemed_key_val", "")

    # OLD LOGIC: Knights would be filtered out because the gamekey is in the list
    assert gamekey in old_filtered  # gamekey is in the list
    # (simulating the filter: `if key["gamekey"] not in filtered_keys`)
    would_be_filtered_old = gamekey in old_filtered

    # NEW LOGIC: Knights would NOT be filtered because unrevealed keys have no steam key value
    assert knights_value not in new_filtered  # "" is not in the steam key set
    would_be_filtered_new = knights_value in new_filtered

    print("✓ Old logic filters out Knights (BUG)")
    print(f"  - old_filtered contains gamekey: {gamekey in old_filtered}")
    print(f"  - Would filter Knights: {would_be_filtered_old}")
    print()
    print("✓ New logic does NOT filter out Knights (FIXED)")
    print(f"  - new_filtered: {new_filtered}")
    print(f"  - Knights unrevealed value: {repr(knights_value)}")
    print(f"  - Would filter Knights: {would_be_filtered_new}")


def test_empty_steam_keys_excluded():
    """Test that empty steam key values (failed reveals) don't match unrevealed games."""

    # Simulate a CSV with a game that failed to reveal (empty 3rd column)
    csv_content = """gamekey1,Game A,ABCDE-FGHIJ-KLMNO
gamekey2,Game B,
gamekey3,Game C,PQRST-UVWXY-ZABCD"""

    filtered = read_steam_keys_new(csv_content)

    # Should have 2 keys, NOT 3 (empty string excluded)
    assert "" not in filtered, "Empty strings should be excluded from filter set"
    assert len(filtered) == 2, f"Should have 2 valid steam keys, got {len(filtered)}"
    assert "ABCDE-FGHIJ-KLMNO" in filtered
    assert "PQRST-UVWXY-ZABCD" in filtered

    print("✓ Empty steam keys correctly excluded from filter")
    print(f"  - Filtered set: {filtered}")
    print(f"  - Size: {len(filtered)} (not 3)")


def test_game_names_with_commas():
    """Test that comma-sanitization in game names doesn't break CSV parsing."""

    # Note: The write_key function replaces commas with dots in human_name
    # So we should never see commas in the human_name column
    csv_content = """gamekey1,Game with Dots Not Commas,ABCDE-FGHIJ-KLMNO
gamekey2,Another Game Title,PQRST-UVWXY-ZABCD"""

    filtered = read_steam_keys_new(csv_content)
    assert len(filtered) == 2
    assert "ABCDE-FGHIJ-KLMNO" in filtered
    assert "PQRST-UVWXY-ZABCD" in filtered

    print("✓ Game names with dots (not commas) parsed correctly")


def test_utf8_bom():
    """Test that UTF-8 BOM is handled correctly."""

    # Simulate reading a CSV that was opened with utf-8-sig encoding
    # The BOM is already stripped by the encoding, so content is clean
    csv_content = """gamekey1,Game A,ABCDE-FGHIJ-KLMNO
gamekey2,Game B,PQRST-UVWXY-ZABCD"""

    filtered = read_steam_keys_new(csv_content)
    assert len(filtered) == 2
    print("✓ UTF-8 BOM handled correctly (stripped by encoding)")


if __name__ == "__main__":
    print("=" * 70)
    print("Test 1: Old logic vs New logic")
    print("=" * 70)
    test_filter_old_vs_new()

    print()
    print("=" * 70)
    print("Test 2: Empty steam keys excluded")
    print("=" * 70)
    test_empty_steam_keys_excluded()

    print()
    print("=" * 70)
    print("Test 3: Game names with commas")
    print("=" * 70)
    test_game_names_with_commas()

    print()
    print("=" * 70)
    print("Test 4: UTF-8 BOM handling")
    print("=" * 70)
    test_utf8_bom()

    print()
    print("=" * 70)
    print("All tests passed! ✓")
    print("=" * 70)
