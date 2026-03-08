import { Router, Route } from "@solidjs/router";
import { lazy, onMount, type ParentProps } from "solid-js";
import { I18nProvider } from "./i18n";
import { initTheme } from "./stores/theme";
import { fetchCurrentUser } from "./stores/auth";
import Navbar from "./components/layout/Navbar";
import PWAUpdateBanner from "./components/PWAUpdateBanner";

initTheme();

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

function Layout(props: ParentProps) {
  onMount(() => {
    fetchCurrentUser();
  });

  return (
    <>
      <Navbar />
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
        <Route path="/settings" component={Settings} />
        <Route path="/notifications" component={Notifications} />
        <Route path="/admin" component={Admin} />
        <Route path="/drive" component={Drive} />
        <Route path="/bookmarks" component={Bookmarks} />
        <Route path="/search" component={Search} />
        <Route path="/:acct/followers" component={FollowList} />
        <Route path="/:acct/following" component={FollowList} />
        <Route path="/:acct" component={Profile} />
      </Router>
    </I18nProvider>
  );
}
