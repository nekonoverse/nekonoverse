import { createSignal } from "solid-js";
import { useNavigate } from "@solidjs/router";
import { register } from "../../stores/auth";

export default function RegisterForm() {
  const [username, setUsername] = createSignal("");
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
      await register(username(), email(), password());
      navigate("/");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    } finally {
      setLoading(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} class="auth-form">
      <h2>Register</h2>
      {error() && <div class="error">{error()}</div>}
      <div class="field">
        <label for="username">Username</label>
        <input
          id="username"
          type="text"
          value={username()}
          onInput={(e) => setUsername(e.currentTarget.value)}
          pattern="[a-zA-Z0-9_]+"
          required
        />
      </div>
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
          minLength={8}
          required
        />
      </div>
      <button type="submit" disabled={loading()}>
        {loading() ? "Registering..." : "Register"}
      </button>
      <p class="alt-action">
        Already have an account? <a href="/login">Login</a>
      </p>
    </form>
  );
}
