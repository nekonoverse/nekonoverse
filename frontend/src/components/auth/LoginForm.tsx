import { createSignal } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { login } from "../../stores/auth";

export default function LoginForm() {
  const [email, setEmail] = createSignal("");
  const [password, setPassword] = createSignal("");
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);
  const navigate = useNavigate();

  const handleSubmit = async (e: Event) => {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      await login(email(), password());
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Login failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} class="auth-form">
      <h2>Login</h2>
      {error() && <div class="error">{error()}</div>}
      <div class="field">
        <label for="email">Email</label>
        <input
          id="email"
          type="email"
          value={email()}
          onInput={(e) => setEmail(e.currentTarget.value)}
          required
        />
      </div>
      <div class="field">
        <label for="password">Password</label>
        <input
          id="password"
          type="password"
          value={password()}
          onInput={(e) => setPassword(e.currentTarget.value)}
          required
        />
      </div>
      <button type="submit" disabled={loading()}>
        {loading() ? "Logging in..." : "Login"}
      </button>
      <p class="alt-action">
        Don't have an account? <a href="/register">Register</a>
      </p>
    </form>
  );
}
