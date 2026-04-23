"""
M5 Smoke Test — simulate a scored ChangeEvent and verify the matching engine
creates an alert for Sarah's subscription.

Run inside Docker:
    docker compose exec api python scripts/test_m5_matching.py

Safe to re-run — uses a unique hash per execution.
"""
import hashlib
from datetime import datetime, timezone
from uuid import uuid4

from sqlmodel import Session, select, text

from app.database import engine
from app.models import (
    Alert,
    ChangeEvent,
    SourceVersion,
    UserSubscription,
)
from app.services.matching import match_event


def main():
    print("\n" + "=" * 60)
    print("  M5 ALERTING ENGINE — SMOKE TEST")
    print("=" * 60)

    with Session(engine) as session:
        # ── Step 1: Verify Sarah's subscription exists ───────────────
        subs = session.exec(
            select(UserSubscription)
            .where(UserSubscription.user_email == "sarah@acme.com")
        ).all()

        if not subs:
            print("\n❌ No subscription found for sarah@acme.com")
            print("   Run the curl POST command first to create one.")
            return

        print(f"\n✅ Found {len(subs)} subscription(s) for sarah@acme.com")
        for s in subs:
            print(f"   📋 {s.label}")
            print(f"      Topics: {s.topics}")
            print(f"      Origins: {s.origin_countries}")
            print(f"      Keywords: {s.keyword_query}")
            print(f"      Min score: {s.min_significance}")

        # ── Step 2: Create a fake SourceVersion ──────────────────────
        # Use a unique run_id so re-runs don't hit unique constraints.
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
        fake_url = f"https://www.commerce.gov/test-sanctions-update-{run_id}"
        fake_text = (
            "DEPARTMENT OF COMMERCE — Bureau of Industry and Security\n\n"
            "Effective immediately, the United States Department of Commerce "
            "has imposed new restrictions on the export of advanced "
            "microprocessor technology to the People's Republic of China. "
            "Items classified under ECCN 3A090 are now subject to enhanced "
            "end-use screening. Companies exporting lithium-ion battery "
            "components must also file additional documentation under "
            "the new Export Administration Regulations (EAR). "
            "Penalties for non-compliance include fines up to $500,000 "
            f"per violation. [Test run: {run_id}]"
        )
        content_hash = hashlib.sha256(fake_text.encode()).hexdigest()

        sv = SourceVersion(
            id=uuid4(),
            source_url=fake_url,
            source_type="web",
            content_hash=content_hash,
            raw_text=fake_text,
            title="BIS Export Control Update — Microprocessors & Lithium",
            language="en",
        )
        session.add(sv)
        session.flush()
        print(f"\n✅ Created fake SourceVersion: {sv.id}")

        # ── Step 3: Create a fake ChangeEvent (as if M4 scored it) ───
        event = ChangeEvent(
            id=uuid4(),
            source_url=fake_url,
            new_version_id=sv.id,
            diff_kind="created",
            added_chars=len(fake_text),
            removed_chars=0,
            # M4 scoring results:
            significance_score=0.92,
            change_type="critical",
            topic="sanctions_export_control",
            summary="BIS restricts export of microprocessors and lithium "
                    "battery components to China under ECCN 3A090.",
            trade_flow_direction="outbound",
            origin_countries=["US"],
            destination_countries=["CN"],
            affected_entities=["ECCN 3A090", "BIS", "EAR"],
            scored_at=datetime.now(timezone.utc),
            llm_model="test-simulation",
        )
        session.add(event)
        session.commit()
        print(f"✅ Created fake ChangeEvent: {event.id}")
        print(f"   Topic: {event.topic}")
        print(f"   Score: {event.significance_score}")
        print(f"   Trade: {event.origin_countries} → {event.destination_countries}")

        # ── Step 4: Run the M5 Matching Engine ───────────────────────
        print("\n🔍 Running M5 matching engine...")
        result = match_event(event.id)
        print(f"   Result: {result}")

        # ── Step 5: Check if alerts were created ─────────────────────
        alerts = session.exec(
            select(Alert)
            .where(Alert.change_event_id == event.id)
        ).all()

        if alerts:
            print(f"\n🎉 SUCCESS! {len(alerts)} alert(s) created!")
            for a in alerts:
                sub = session.get(UserSubscription, a.subscription_id)
                print(f"   🔔 Alert {a.id}")
                print(f"      For: {sub.user_email if sub else 'unknown'}")
                print(f"      Subscription: {sub.label if sub else 'unknown'}")
                print(f"      Matched keywords: {a.matched_keywords}")
                print(f"      Status: {a.status}")
        else:
            print("\n❌ No alerts created. Check the matching logic.")

        # ── Step 6: Verify via the API endpoint ──────────────────────
        print("\n📡 You can now verify via the API:")
        print('   curl "http://localhost:8001/api/alerts?email=sarah@acme.com"')

    print("\n" + "=" * 60)
    print("  SMOKE TEST COMPLETE")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
