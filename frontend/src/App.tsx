import { Router, Route } from "@solidjs/router";
import { lazy, type ParentProps } from "solid-js";
import { I18nProvider } from "./i18n";
import { initTheme } from "./stores/theme";
import Navbar from "./components/layout/Navbar";

initTheme();

const Home = lazy(() => import("./pages/Home"));
const Login = lazy(() => import("./pages/Login"));
const Register = lazy(() => import("./pages/Register"));
const Settings = lazy(() => import("./pages/Settings"));

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
      <Router root={Layout}>
        <Route path="/" component={Home} />
        <Route path="/login" component={Login} />
        <Route path="/register" component={Register} />
        <Route path="/settings" component={Settings} />
      </Router>
    </I18nProvider>
  );
}
