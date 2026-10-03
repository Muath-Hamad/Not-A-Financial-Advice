// Sign in (docs/08 §9): username, password and the 6-digit authenticator
// code. Five failures lock the account for 15 minutes.

import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { postJson, setCsrf, keys } from '@/api/client';
import { Note } from '@/components/ui';
import { T } from '@/glossary/Term';
import type { Theme } from './console';

export function Login({ theme }: { theme: Theme }) {
  const qc = useQueryClient();
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [code, setCode] = useState('');
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await postJson<{ csrf: string }>('/api/auth/login', { username, password, code });
      setCsrf(r.csrf);
      await qc.invalidateQueries({ queryKey: keys.me });
    } catch (x) {
      setErr((x as Error).message);
      setCode('');
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="nafa app" data-theme={theme} style={{ height: '100vh', display: 'grid', placeItems: 'center', padding: 16 }}>
      <form className="panel" style={{ width: 380, maxWidth: '100%' }} onSubmit={submit}>
        <div className="ph"><span className="brand-mark">N</span><h3>NAFA Console</h3><span className="hint">sign in</span></div>
        <div className="pb col" style={{ gap: 12 }}>
          <div className="fld"><label className="lbl" htmlFor="u">Username</label><input id="u" className="inp" style={{ height: 38 }} autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} autoFocus /></div>
          <div className="fld"><label className="lbl" htmlFor="p">Password</label><input id="p" className="inp" style={{ height: 38 }} type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} /></div>
          <div className="fld">
            <label className="lbl" htmlFor="c">Authenticator code (<T k="totp">TOTP</T>)</label>
            <input id="c" className="totp" inputMode="numeric" autoComplete="one-time-code" placeholder="••••••" value={code} onChange={(e) => setCode(e.target.value.replace(/[^0-9]/g, '').slice(0, 6))} />
          </div>
          {err && <Note tone="danger">{err}</Note>}
          <button type="submit" className="btn primary lg" disabled={busy || !username || !password || code.length !== 6}>{busy ? 'Signing in…' : 'Sign in'}</button>
          <span className="xs muted">LAN or Tailscale only. Five failed attempts lock the account for 15 minutes. New users: <span className="mono">python -m nafa_console.users add</span>.</span>
        </div>
      </form>
    </div>
  );
}
