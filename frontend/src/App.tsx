import { Router, Route } from "@solidjs/router";
import { lazy } from "solid-js";
import { I18nProvider } from "./i18n";
import LanguageSwitcher from "./components/layout/LanguageSwitcher";

const Home = lazy(() => import("./pages/Home"));
const Login = lazy(() => import("./pages/Login"));
const Register = lazy(() => import("./pages/Register"));

export default function App() {
  return (
    <I18nProvider>
      <LanguageSwitcher />
      <Router>
        <Route path="/" component={Home} />
        <Route path="/login" component={Login} />
        <Route path="/register" component={Register} />
      </Router>
    </I18nProvider>
  );
}
