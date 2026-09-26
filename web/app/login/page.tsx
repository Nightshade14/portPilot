import { isGateConfigured } from "@/lib/auth";
import { loginAction } from "./actions";
import styles from "./login.module.css";

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ next?: string; error?: string }>;
}) {
  const params = await searchParams;
  const next = params.next ?? "/";
  const hasError = params.error === "1";
  const gateOpen = !isGateConfigured();

  return (
    <main className={styles.main}>
      <h1>PortPilot</h1>
      {gateOpen ? (
        <p className={styles.banner} role="status">
          Development mode: no passcode is configured, so the access gate is open. Set{" "}
          <code>PORTPILOT_UI_PASSCODE</code> to require one.
        </p>
      ) : (
        <form action={loginAction} className={styles.form}>
          <label htmlFor="passcode">Passcode</label>
          <input
            id="passcode"
            name="passcode"
            type="password"
            required
            autoComplete="current-password"
            aria-describedby={hasError ? "passcode-error" : undefined}
          />
          <input type="hidden" name="next" value={next} />
          {hasError ? (
            <p id="passcode-error" role="alert" className={styles.error}>
              Incorrect passcode.
            </p>
          ) : null}
          <button type="submit">Sign in</button>
        </form>
      )}
    </main>
  );
}
