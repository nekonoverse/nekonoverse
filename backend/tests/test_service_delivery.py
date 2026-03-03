async def test_enqueue_creates_job(db, test_user, mock_valkey):
    from app.services.delivery_service import enqueue_delivery
    job = await enqueue_delivery(
        db, test_user.actor_id, "http://remote.example/inbox",
        {"type": "Create", "object": "..."}
    )
    assert job.status == "pending"
    assert job.target_inbox_url == "http://remote.example/inbox"


async def test_enqueue_notifies_valkey(db, test_user, mock_valkey):
    from app.services.delivery_service import enqueue_delivery
    job = await enqueue_delivery(
        db, test_user.actor_id, "http://remote.example/inbox", {"type": "Create"}
    )
    mock_valkey.lpush.assert_called_with("delivery:queue", str(job.id))


async def test_enqueue_stores_payload(db, test_user, mock_valkey):
    from app.services.delivery_service import enqueue_delivery
    payload = {"type": "Follow", "actor": "a", "object": "b"}
    job = await enqueue_delivery(db, test_user.actor_id, "http://r.example/inbox", payload)
    assert job.payload == payload


async def test_enqueue_defaults(db, test_user, mock_valkey):
    from app.services.delivery_service import enqueue_delivery
    job = await enqueue_delivery(db, test_user.actor_id, "http://r.example/inbox", {})
    assert job.attempts == 0
