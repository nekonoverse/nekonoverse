import { onMount } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { currentUser } from "../stores/auth";
import LoginForm from "../components/auth/LoginForm";

export default function Login() {
  const navigate = useNavigate();

  onMount(() => {
    if (currentUser()) navigate("/", { replace: true });
  });

  return (
    <div class="page-container">
      <LoginForm />
    </div>
  );
}
