import { Router, Route, useIsRouting } from "@solidjs/router";
import { lazy, onMount, onCleanup, createEffect, createSignal, Show, Suspense, type ParentProps } from "solid-js";
import { I18nProvider } from "@nekonoverse/ui/i18n";
import { initTheme, inputMode } from "@nekonoverse/ui/stores/theme";
import { fetchCurrentUser, currentUser } from "@nekonoverse/ui/stores/auth";
import {
  instance,
  fetchInstance,
  checkClientVersion,
  startVersionPolling,
} from "@nekonoverse/ui/stores/instance";
import Navbar from "./components/layout/Navbar";
import SwipeBack from "./components/SwipeBack";
import PWAUpdateBanner from "./components/PWAUpdateBanner";
import InputModeModal from "./components/InputModeModal";

initTheme();
checkClientVersion();

const Home = lazy(() => import("./pages/Home"));
const Login = lazy(() => import("./pages/Login"));
const Register = lazy(() => import("./pages/Register"));
const Settings = lazy(() => import("./pages/Settings"));
const Notifications = lazy(() => import("./pages/Notifications"));
const Admin = lazy(() => import("./pages/Admin"));
const Drive = lazy(() => import("./pages/Drive"));
const Bookmarks = lazy(() => import("./pages/Bookmarks"));
const Search = lazy(() => import("./pages/Search"));
const Profile = lazy(() => import("./pages/Profile"));
const FollowList = lazy(() => import("./pages/FollowList"));
const FollowRequests = lazy(() => import("./pages/FollowRequests"));
const TagTimeline = lazy(() => import("./pages/TagTimeline"));
const NoteThread = lazy(() => import("./pages/NoteThread"));
const Terms = lazy(() => import("./pages/Terms"));
const Privacy = lazy(() => import("./pages/Privacy"));
const ForgotPassword = lazy(() => import("./pages/ForgotPassword"));
const ResetPassword = lazy(() => import("./pages/ResetPassword"));
const VerifyEmail = lazy(() => import("./pages/VerifyEmail"));

function NavigationProgress() {
  const isRouting = useIsRouting();
  const [visible, setVisible] = createSignal(false);
  const [width, setWidth] = createSignal(0);
  let hideTimer: ReturnType<typeof setTimeout> | undefined;
  let growTimer: ReturnType<typeof setInterval> | undefined;

  createEffect(() => {
    if (isRouting()) {
      // ルーティング開始 → バー表示
      clearTimeout(hideTimer);
      setVisible(true);
      setWidth(30);
      clearInterval(growTimer);
      growTimer = setInterval(() => {
        setWidth((w) => (w < 90 ? w + (90 - w) * 0.1 : w));
      }, 100);
    } else if (visible()) {
      // ルーティング完了 → 100%にしてフェードアウト
      clearInterval(growTimer);
      setWidth(100);
      hideTimer = setTimeout(() => setVisible(false), 200);
    }
  });

  onCleanup(() => {
    clearTimeout(hideTimer);
    clearInterval(growTimer);
  });

  return (
    <Show when={visible()}>
      <div class="nav-progress-bar" style={{ width: `${width()}%` }} />
    </Show>
  );
}

function Layout(props: ParentProps) {
  onMount(() => {
    fetchCurrentUser();
    fetchInstance();
  });

  createEffect(() => {
    const info = instance();
    if (info?.title) {
      document.title = info.title;
    }
  });

  const stopPolling = startVersionPolling();
  onCleanup(stopPolling);

  return (
    <>
      <NavigationProgress />
      <Navbar />
      <SwipeBack />
      <Suspense>{props.children}</Suspense>
    </>
  );
}

export default function App() {
  const [dismissed, setDismissed] = createSignal(false);
  const needsInputMode = () => !dismissed() && inputMode() === null && !!currentUser();

  return (
    <I18nProvider>
      <PWAUpdateBanner />
      <Show when={needsInputMode()}>
        <InputModeModal onClose={() => setDismissed(true)} />
      </Show>
      <Router root={Layout}>
        <Route path="/" component={Home} />
        <Route path="/login" component={Login} />
        <Route path="/register" component={Register} />
        <Route path="/forgot-password" component={ForgotPassword} />
        <Route path="/reset-password" component={ResetPassword} />
        <Route path="/verify-email" component={VerifyEmail} />
        <Route path="/settings/*section" component={Settings} />
        <Route path="/notifications" component={Notifications} />
        <Route path="/mentions" component={Notifications} />
        <Route path="/admin/*section" component={Admin} />
        <Route path="/drive" component={Drive} />
        <Route path="/bookmarks" component={Bookmarks} />
        <Route path="/follow-requests" component={FollowRequests} />
        <Route path="/search" component={Search} />
        <Route path="/terms" component={Terms} />
        <Route path="/privacy" component={Privacy} />
        <Route path="/tags/:tag" component={TagTimeline} />
        <Route path="/notes/:id" component={NoteThread} />
        <Route path="/:acct/followers" component={FollowList} />
        <Route path="/:acct/following" component={FollowList} />
        <Route path="/:acct" component={Profile} />
      </Router>
    </I18nProvider>
  );
}
