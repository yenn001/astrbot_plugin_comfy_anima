import json
import itertools
from pathlib import Path
import tempfile
import time
import unittest

from ..services.danbooru_character_profile import (
    CharacterAppearanceProfileStore,
    build_character_appearance_profile,
)


_POST_IDS = itertools.count(1)


def _post(
    *tags: str,
    character: str = "rio_(blue_archive)",
    rating: str = "g",
    post_id: int | None = None,
    **state,
):
    return {
        "id": next(_POST_IDS) if post_id is None else post_id,
        "rating": rating,
        "tag_string_character": character,
        "tag_string_general": " ".join(tags),
        "is_deleted": False,
        "is_pending": False,
        "is_flagged": False,
        **state,
    }


class DanbooruCharacterProfileTests(unittest.TestCase):
    def test_rio_profile_keeps_only_stable_supported_appearance(self) -> None:
        posts = []
        for index in range(100):
            tags = ["1girl", "solo", "black_hair", "red_eyes", "long_hair"]
            if index < 85:
                tags.append("halo")
            if index < 75:
                tags.extend(("white_sweater", "large_breasts"))
            if index < 40:
                tags.append("hairclip")
            posts.append(_post(*tags))

        profile = build_character_appearance_profile(
            "rio_(blue_archive)",
            posts,
            fetched_at=1000.0,
        )

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(
            profile.appearance_tags,
            ("black hair", "red eyes", "long hair", "halo"),
        )
        self.assertEqual(profile.sample_count, 100)
        self.assertNotIn("white sweater", profile.appearance_tags)
        self.assertNotIn("large breasts", profile.appearance_tags)
        self.assertNotIn("hairclip", profile.appearance_tags)

    def test_wrong_character_and_non_safe_posts_do_not_count(self) -> None:
        posts = [
            *[
                _post("solo", "black_hair", "red_eyes", "long_hair")
                for _ in range(11)
            ],
            _post(
                "solo",
                "white_hair",
                "blue_eyes",
                "long_hair",
                character="toki_(blue_archive)",
            ),
            _post("solo", "black_hair", "red_eyes", "long_hair", rating="q"),
        ]

        self.assertIsNone(build_character_appearance_profile("rio_(blue_archive)", posts))

    def test_only_unique_active_safe_solo_single_character_posts_count(self) -> None:
        valid = [
            _post("solo", "black_hair", "red_eyes", "long_hair", "halo")
            for _ in range(12)
        ]
        invalid = [
            _post("solo", "black_hair", "red_eyes", rating=""),
            _post("black_hair", "red_eyes", "long_hair"),
            _post(
                "solo",
                "black_hair",
                "red_eyes",
                character="rio_(blue_archive) toki_(blue_archive)",
            ),
            _post("solo", "black_hair", "red_eyes", is_deleted=True),
            _post("solo", "black_hair", "red_eyes", is_pending=True),
            _post("solo", "black_hair", "red_eyes", is_flagged=True),
            _post(
                "solo",
                "white_hair",
                "blue_eyes",
                post_id=valid[0]["id"],
            ),
        ]

        profile = build_character_appearance_profile(
            "rio_(blue_archive)",
            (*valid, *invalid),
        )

        self.assertIsNotNone(profile)
        assert profile is not None
        self.assertEqual(profile.sample_count, 12)
        self.assertEqual(
            profile.appearance_tags,
            ("black hair", "red eyes", "long hair", "halo"),
        )

    def test_duplicate_post_ids_cannot_satisfy_minimum_samples(self) -> None:
        posts = [
            _post(
                "solo",
                "black_hair",
                "red_eyes",
                "long_hair",
                post_id=99,
            )
            for _ in range(12)
        ]

        self.assertIsNone(build_character_appearance_profile("rio_(blue_archive)", posts))

    def test_store_round_trip_and_expiry(self) -> None:
        posts = [
            _post("solo", "black_hair", "red_eyes", "long_hair", "halo")
            for _ in range(12)
        ]
        profile = build_character_appearance_profile(
            "rio_(blue_archive)",
            posts,
            fetched_at=time.time(),
        )
        assert profile is not None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            store = CharacterAppearanceProfileStore(path, ttl_seconds=3600)
            store.put(profile)
            loaded = store.get("rio_\\(blue_archive\\)")
            self.assertEqual(loaded, profile)
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload["profiles"]["rio_(blue_archive)"]["fetched_at"] = 1.0
            path.write_text(json.dumps(payload), encoding="utf-8")
            self.assertIsNone(store.get("rio_(blue_archive)"))

    def test_store_rejects_cross_character_and_untrusted_cached_profiles(self) -> None:
        posts = [
            _post("solo", "black_hair", "red_eyes", "long_hair", "halo")
            for _ in range(12)
        ]
        profile = build_character_appearance_profile(
            "rio_(blue_archive)",
            posts,
            fetched_at=time.time(),
        )
        assert profile is not None
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profiles.json"
            store = CharacterAppearanceProfileStore(path, ttl_seconds=3600)
            store.put(profile)
            original = json.loads(path.read_text(encoding="utf-8"))
            mutations = (
                ("cross canonical", lambda row: row.__setitem__("canonical_tag", "toki_(blue_archive)")),
                ("untrusted source", lambda row: row.__setitem__("source", "provider")),
                ("prompt injection", lambda row: row["appearance_tags"].__setitem__(0, "<lora:bad:1>")),
                ("support mismatch", lambda row: row["support"][0].__setitem__(0, "red eyes")),
                ("future timestamp", lambda row: row.__setitem__("fetched_at", time.time() + 3600)),
            )
            for label, mutate in mutations:
                with self.subTest(label=label):
                    payload = json.loads(json.dumps(original))
                    row = payload["profiles"]["rio_(blue_archive)"]
                    mutate(row)
                    path.write_text(json.dumps(payload), encoding="utf-8")
                    self.assertIsNone(store.get("rio_(blue_archive)"))


if __name__ == "__main__":
    unittest.main()
