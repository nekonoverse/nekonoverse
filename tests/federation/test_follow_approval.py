"""Federation tests for follow request (locked account) scenarios.

Covers: approve, reject, cancel, block while pending,
block+unblock existing follower, disable locked mode (auto-approve).
"""

from conftest import (
    INSTANCE_A,
    INSTANCE_A_DOMAIN,
    INSTANCE_B,
    INSTANCE_B_DOMAIN,
    InstanceClient,
    poll_until,
)


# ── 1. Follow request approved ──────────────────────────────────────────


class TestFollowApprove:
    """dave@A (locked) ← eve@B follows → dave approves."""

    def test_01_setup(self, instance_a, instance_b):
        dave = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        dave.register("dave", "dave@example.com", "password1234", "Dave")
        dave.login("dave", "password1234")
        dave.update_credentials(locked="true")
        creds = dave.verify_credentials()
        assert creds["locked"] is True

        eve = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        eve.register("eve", "eve@example.com", "password1234", "Eve")
        eve.login("eve", "password1234")

    def test_02_send_follow_request(self, instance_a, instance_b):
        eve = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        eve.login("eve", "password1234")

        accounts = eve.search_accounts(f"dave@{INSTANCE_A_DOMAIN}", resolve=True)
        assert len(accounts) >= 1
        dave_remote_id = accounts[0]["id"]
        self.__class__.dave_remote_id_on_b = dave_remote_id

        eve.follow(dave_remote_id)

        # Wait for pending request to arrive on instance-a
        dave = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        dave.login("dave", "password1234")
        poll_until(
            lambda: len(dave.get_follow_requests()) > 0,
            timeout=15,
            desc="follow request to arrive on instance-a",
        )
        requests = dave.get_follow_requests()
        assert len(requests) == 1
        self.__class__.eve_actor_id_on_a = requests[0]["id"]

    def test_03_approve(self):
        dave = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        dave.login("dave", "password1234")

        result = dave.authorize_follow_request(self.eve_actor_id_on_a)
        assert result["followed_by"] is True

        # Pending list should be empty
        assert len(dave.get_follow_requests()) == 0

    def test_04_verify_on_both_instances(self, instance_a):
        # AP: dave has 1 follower
        poll_until(
            lambda: instance_a.get_followers("dave")["totalItems"] >= 1,
            timeout=15,
            desc="dave to have 1 follower (AP)",
        )

        # instance-b: eve sees following=True
        eve = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        eve.login("eve", "password1234")
        poll_until(
            lambda: eve.get_relationship(self.dave_remote_id_on_b).get("following") is True,
            timeout=15,
            desc="eve to see following=True on instance-b",
        )


# ── 2. Follow request rejected ──────────────────────────────────────────


class TestFollowReject:
    """frank@A (locked) ← grace@B follows → frank rejects."""

    def test_01_setup(self, instance_a, instance_b):
        frank = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        frank.register("frank", "frank@example.com", "password1234", "Frank")
        frank.login("frank", "password1234")
        frank.update_credentials(locked="true")

        grace = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        grace.register("grace", "grace@example.com", "password1234", "Grace")
        grace.login("grace", "password1234")

    def test_02_send_and_reject(self, instance_a):
        grace = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        grace.login("grace", "password1234")

        accounts = grace.search_accounts(f"frank@{INSTANCE_A_DOMAIN}", resolve=True)
        assert len(accounts) >= 1
        frank_remote_id = accounts[0]["id"]
        self.__class__.frank_remote_id_on_b = frank_remote_id

        grace.follow(frank_remote_id)

        frank = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        frank.login("frank", "password1234")
        poll_until(
            lambda: len(frank.get_follow_requests()) > 0,
            timeout=15,
            desc="follow request to arrive",
        )
        requests = frank.get_follow_requests()
        grace_actor_id = requests[0]["id"]

        result = frank.reject_follow_request(grace_actor_id)
        assert result["followed_by"] is False

    def test_03_verify_no_follow(self, instance_a):
        frank = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        frank.login("frank", "password1234")
        assert len(frank.get_follow_requests()) == 0
        assert instance_a.get_followers("frank")["totalItems"] == 0

        # instance-b: grace sees requested=False, following=False
        grace = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        grace.login("grace", "password1234")
        poll_until(
            lambda: grace.get_relationship(self.frank_remote_id_on_b).get("requested") is False,
            timeout=15,
            desc="grace to see requested=False after reject",
        )
        rel = grace.get_relationship(self.frank_remote_id_on_b)
        assert rel["following"] is False


# ── 3. Cancel follow request (unfollow = withdraw) ──────────────────────


class TestCancelFollowRequest:
    """hank@A (locked) ← iris@B follows → iris withdraws (unfollow)."""

    def test_01_setup(self, instance_a, instance_b):
        hank = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        hank.register("hank", "hank@example.com", "password1234", "Hank")
        hank.login("hank", "password1234")
        hank.update_credentials(locked="true")

        iris = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        iris.register("iris", "iris@example.com", "password1234", "Iris")
        iris.login("iris", "password1234")

    def test_02_send_then_cancel(self):
        iris = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        iris.login("iris", "password1234")

        accounts = iris.search_accounts(f"hank@{INSTANCE_A_DOMAIN}", resolve=True)
        assert len(accounts) >= 1
        hank_remote_id = accounts[0]["id"]
        self.__class__.hank_remote_id_on_b = hank_remote_id

        iris.follow(hank_remote_id)

        hank = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        hank.login("hank", "password1234")
        poll_until(
            lambda: len(hank.get_follow_requests()) > 0,
            timeout=15,
            desc="follow request to arrive",
        )

        # iris cancels
        iris.unfollow(hank_remote_id)

    def test_03_verify_request_removed(self, instance_a):
        hank = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        hank.login("hank", "password1234")

        # Undo(Follow) should clear the pending request
        poll_until(
            lambda: len(hank.get_follow_requests()) == 0,
            timeout=15,
            desc="pending request to be removed after cancel",
        )
        assert instance_a.get_followers("hank")["totalItems"] == 0

        iris = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        iris.login("iris", "password1234")
        rel = iris.get_relationship(self.hank_remote_id_on_b)
        assert rel["following"] is False
        assert rel["requested"] is False


# ── 4. Block while request pending ──────────────────────────────────────


class TestBlockWhilePending:
    """jack@A (locked) ← kate@B follows → jack blocks kate."""

    def test_01_setup(self, instance_a, instance_b):
        jack = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        jack.register("jack", "jack@example.com", "password1234", "Jack")
        jack.login("jack", "password1234")
        jack.update_credentials(locked="true")

        kate = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        kate.register("kate", "kate@example.com", "password1234", "Kate")
        kate.login("kate", "password1234")

    def test_02_send_then_block(self):
        kate = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        kate.login("kate", "password1234")

        accounts = kate.search_accounts(f"jack@{INSTANCE_A_DOMAIN}", resolve=True)
        assert len(accounts) >= 1
        jack_remote_id = accounts[0]["id"]
        self.__class__.jack_remote_id_on_b = jack_remote_id

        kate.follow(jack_remote_id)

        jack = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        jack.login("jack", "password1234")
        poll_until(
            lambda: len(jack.get_follow_requests()) > 0,
            timeout=15,
            desc="follow request to arrive",
        )

        # Get kate's actor ID from the pending requests
        requests = jack.get_follow_requests()
        kate_actor_id = requests[0]["id"]
        self.__class__.kate_actor_id_on_a = kate_actor_id

        jack.block(kate_actor_id)

    def test_03_verify_block_and_no_follow(self, instance_a):
        jack = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        jack.login("jack", "password1234")

        # Pending request removed by block
        assert len(jack.get_follow_requests()) == 0
        assert instance_a.get_followers("jack")["totalItems"] == 0

        # jack is blocking kate
        rel = jack.get_relationship(self.kate_actor_id_on_a)
        assert rel["blocking"] is True
        assert rel["followed_by"] is False

        # kate sees follow removed
        kate = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        kate.login("kate", "password1234")
        poll_until(
            lambda: kate.get_relationship(self.jack_remote_id_on_b).get("following") is False
            and kate.get_relationship(self.jack_remote_id_on_b).get("requested") is False,
            timeout=15,
            desc="kate to see follow removed after block",
        )


# ── 5. Block then unblock existing follower ─────────────────────────────


class TestBlockThenUnblock:
    """leo@A (unlocked) ← mona@B follows (auto-accept) → leo blocks → unblocks."""

    def test_01_setup(self, instance_a, instance_b):
        leo = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        leo.register("leo", "leo@example.com", "password1234", "Leo")
        leo.login("leo", "password1234")
        # NOT locked — follow auto-accepts

        mona = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        mona.register("mona", "mona@example.com", "password1234", "Mona")
        mona.login("mona", "password1234")

    def test_02_follow_auto_accepted(self, instance_a):
        mona = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        mona.login("mona", "password1234")

        accounts = mona.search_accounts(f"leo@{INSTANCE_A_DOMAIN}", resolve=True)
        assert len(accounts) >= 1
        leo_remote_id = accounts[0]["id"]
        self.__class__.leo_remote_id_on_b = leo_remote_id

        mona.follow(leo_remote_id)

        # Wait for auto-accept delivery
        poll_until(
            lambda: instance_a.get_followers("leo")["totalItems"] >= 1,
            timeout=15,
            desc="mona's follow to be auto-accepted",
        )

        # Resolve mona on instance-a for later block
        leo = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        leo.login("leo", "password1234")
        mona_accounts = leo.search_accounts(f"mona@{INSTANCE_B_DOMAIN}", resolve=True)
        assert len(mona_accounts) >= 1
        self.__class__.mona_actor_id_on_a = mona_accounts[0]["id"]

    def test_03_block(self, instance_a):
        leo = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        leo.login("leo", "password1234")

        leo.block(self.mona_actor_id_on_a)

        # Follow removed
        poll_until(
            lambda: instance_a.get_followers("leo")["totalItems"] == 0,
            timeout=15,
            desc="follow to be removed after block",
        )
        rel = leo.get_relationship(self.mona_actor_id_on_a)
        assert rel["blocking"] is True
        assert rel["followed_by"] is False

        # mona sees follow gone
        mona = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        mona.login("mona", "password1234")
        poll_until(
            lambda: mona.get_relationship(self.leo_remote_id_on_b).get("following") is False,
            timeout=15,
            desc="mona to see follow removed",
        )

    def test_04_unblock_no_refollow(self, instance_a):
        leo = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        leo.login("leo", "password1234")

        leo.unblock(self.mona_actor_id_on_a)

        # Verify block is removed
        poll_until(
            lambda: leo.get_relationship(self.mona_actor_id_on_a).get("blocking") is False,
            timeout=15,
            desc="block to be removed",
        )

        # Follow must NOT be restored
        assert instance_a.get_followers("leo")["totalItems"] == 0
        rel = leo.get_relationship(self.mona_actor_id_on_a)
        assert rel["followed_by"] is False

        mona = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        mona.login("mona", "password1234")
        rel_b = mona.get_relationship(self.leo_remote_id_on_b)
        assert rel_b["following"] is False


# ── 6. Disable locked mode → auto-approve ───────────────────────────────


class TestDisableLocked:
    """nick@A (locked) ← olive@B, pat@B follow → nick unlocks → auto-approve."""

    def test_01_setup(self, instance_a, instance_b):
        nick = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        nick.register("nick", "nick@example.com", "password1234", "Nick")
        nick.login("nick", "password1234")
        nick.update_credentials(locked="true")

        olive = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        olive.register("olive", "olive@example.com", "password1234", "Olive")
        olive.login("olive", "password1234")

        pat = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        pat.register("pat", "pat@example.com", "password1234", "Pat")
        pat.login("pat", "password1234")

    def test_02_send_multiple_requests(self):
        nick = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        nick.login("nick", "password1234")

        olive = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        olive.login("olive", "password1234")
        accounts_o = olive.search_accounts(f"nick@{INSTANCE_A_DOMAIN}", resolve=True)
        assert len(accounts_o) >= 1
        nick_remote_id = accounts_o[0]["id"]
        self.__class__.nick_remote_id_on_b = nick_remote_id

        olive.follow(nick_remote_id)

        pat = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        pat.login("pat", "password1234")
        accounts_p = pat.search_accounts(f"nick@{INSTANCE_A_DOMAIN}", resolve=True)
        assert len(accounts_p) >= 1
        pat.follow(accounts_p[0]["id"])

        # Wait for both requests
        poll_until(
            lambda: len(nick.get_follow_requests()) >= 2,
            timeout=20,
            desc="2 follow requests to arrive",
        )

    def test_03_disable_locked(self):
        nick = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        nick.login("nick", "password1234")

        nick.update_credentials(locked="false")
        creds = nick.verify_credentials()
        assert creds["locked"] is False

    def test_04_verify_auto_approve(self, instance_a):
        nick = InstanceClient(INSTANCE_A, INSTANCE_A_DOMAIN)
        nick.login("nick", "password1234")

        # All pending requests should be auto-approved
        poll_until(
            lambda: len(nick.get_follow_requests()) == 0,
            timeout=15,
            desc="pending requests to be auto-approved",
        )

        # AP: nick has 2 followers
        poll_until(
            lambda: instance_a.get_followers("nick")["totalItems"] >= 2,
            timeout=20,
            desc="nick to have 2 followers",
        )

        # Both olive and pat see following=True
        olive = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        olive.login("olive", "password1234")
        poll_until(
            lambda: olive.get_relationship(self.nick_remote_id_on_b).get("following") is True,
            timeout=20,
            desc="olive to see following=True",
        )

        pat = InstanceClient(INSTANCE_B, INSTANCE_B_DOMAIN)
        pat.login("pat", "password1234")
        pat_accounts = pat.search_accounts(f"nick@{INSTANCE_A_DOMAIN}", resolve=True)
        nick_id_for_pat = pat_accounts[0]["id"]
        poll_until(
            lambda: pat.get_relationship(nick_id_for_pat).get("following") is True,
            timeout=20,
            desc="pat to see following=True",
        )
