from __future__ import annotations

import pytest

from orca.memory.consent import MemoryConsentError, require_consent


def test_memory_write_and_search_need_explicit_consent():
    ok = require_consent(user_id="user-a", granted=True, purpose="long_term")
    assert ok["granted"] is True
    with pytest.raises(MemoryConsentError) as exc:
        require_consent(user_id="user-a", granted=False, purpose="long_term")
    assert exc.value.code == "consent_required"
    with pytest.raises(MemoryConsentError) as exc:
        require_consent(user_id="", granted=True, purpose="search")
    assert exc.value.code == "unauthenticated"
    with pytest.raises(MemoryConsentError) as exc:
        require_consent(user_id="user-a", granted=True, purpose="exfiltrate")
    assert exc.value.code == "purpose_refused"
