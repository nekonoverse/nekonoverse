import { createSignal, onCleanup, Show } from "solid-js";
import { getAccount, type Account } from "../api/accounts";

interface Props {
  actorId: string;
  children: any;
}

// Simple in-memory cache
const cache = new Map<string, Account>();

export default function UserHoverCard(props: Props) {
  const [visible, setVisible] = createSignal(false);
  const [account, setAccount] = createSignal<Account | null>(null);
  let showTimer: number | undefined;
  let hideTimer: number | undefined;

  const fetchAccount = async () => {
    const cached = cache.get(props.actorId);
    if (cached) {
      setAccount(cached);
      return;
    }
    try {
      const acc = await getAccount(props.actorId);
      cache.set(props.actorId, acc);
      setAccount(acc);
    } catch {}
  };

  const handleMouseEnter = () => {
    clearTimeout(hideTimer);
    showTimer = window.setTimeout(() => {
      setVisible(true);
      if (!account()) fetchAccount();
    }, 300);
  };

  const handleMouseLeave = () => {
    clearTimeout(showTimer);
    hideTimer = window.setTimeout(() => setVisible(false), 200);
  };

  onCleanup(() => {
    clearTimeout(showTimer);
    clearTimeout(hideTimer);
  });

  return (
    <span
      class="hover-card-wrapper"
      onMouseEnter={handleMouseEnter}
      onMouseLeave={handleMouseLeave}
    >
      {props.children}
      <Show when={visible()}>
        <div
          class="hover-card"
          onMouseEnter={() => clearTimeout(hideTimer)}
          onMouseLeave={handleMouseLeave}
        >
          <Show when={account()} fallback={<div class="hover-card-loading" />}>
            {(() => {
              const acc = account()!;
              return (
                <>
                  <div class="hover-card-header">
                    <img
                      class="hover-card-avatar"
                      src={acc.avatar || "/default-avatar.svg"}
                      alt=""
                    />
                    <div class="hover-card-names">
                      <strong class="hover-card-display-name">
                        {acc.display_name || acc.username}
                      </strong>
                      <span class="hover-card-handle">@{acc.acct}</span>
                    </div>
                  </div>
                  <Show when={acc.note}>
                    <p class="hover-card-bio" innerHTML={acc.note} />
                  </Show>
                </>
              );
            })()}
          </Show>
        </div>
      </Show>
    </span>
  );
}
