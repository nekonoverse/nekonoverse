import { Router, Route } from "@solidjs/router";
import { lazy, type ParentProps } from "solid-js";
import { I18nProvider } from "./i18n";
import { initTheme } from "./stores/theme";
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
const Profile = lazy(() => import("./pages/Profile"));

function Layout(props: ParentProps) {
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
        <Route path="/:acct" component={Profile} />
      </Router>
    </I18nProvider>
  );
}
