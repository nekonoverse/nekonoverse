import { Router, Route } from "@solidjs/router";
import { lazy, onMount, onCleanup, type ParentProps } from "solid-js";
import { I18nProvider } from "@nekonoverse/ui/i18n";
import { initTheme } from "@nekonoverse/ui/stores/theme";
import { fetchCurrentUser } from "@nekonoverse/ui/stores/auth";
import {
  fetchInstance,
  checkClientVersion,
  startVersionPolling,
} from "@nekonoverse/ui/stores/instance";
import Navbar from "./components/layout/Navbar";
import SwipeBack from "./components/SwipeBack";
import PWAUpdateBanner from "./components/PWAUpdateBanner";

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

function Layout(props: ParentProps) {
  onMount(() => {
    fetchCurrentUser();
    fetchInstance();
  });

  const stopPolling = startVersionPolling();
  onCleanup(stopPolling);

  return (
    <>
      <Navbar />
      <SwipeBack />
      {props.children}
    </>
  );
}

export default function App() {
  return (
    <I18nProvider>
      <PWAUpdateBanner />
      <Router root={Layout}>
        <Route path="/" component={Home} />
        <Route path="/login" component={Login} />
        <Route path="/register" component={Register} />
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
