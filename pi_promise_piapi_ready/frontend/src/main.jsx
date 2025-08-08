import React, {useState} from "react"; import {createRoot} from "react-dom/client";
const API = import.meta.env.VITE_API_URL || "http://localhost:8000";
function App(){
  const [token,setToken] = useState(localStorage.getItem("pip_token")||"");
  const [piName,setPiName] = useState("");
  const [proof,setProof] = useState("");
  const [msg,setMsg] = useState(""); const [me,setMe]=useState(null);
  async function connectPi(){
    // Send pi_name and proof to server. In production, proof should be wallet-signed token.
    const res = await fetch(`${API}/auth/pi`, {method:"POST", headers:{"Content-Type":"application/json"}, body:JSON.stringify({pi_name: piName, proof: proof})});
    const j = await res.json();
    if(res.ok && j.token){ localStorage.setItem("pip_token", j.token); setToken(j.token); setMsg("Connected"); fetchMe(j.token) } else { setMsg("Connect failed: " + (j.detail || JSON.stringify(j))) }
  }
  async function fetchMe(tok){ const r = await fetch(`${API}/me?token=${tok}`); if(r.ok){ setMe(await r.json()) } else setMsg("Session invalid") }
  async function mine(){ const r = await fetch(`${API}/mine?token=${token}`, {method:"POST"}); const j = await r.json(); if(j.detail) setMsg(j.detail); else { setMsg("Mined 100 coins"); fetchMe(token) } }
  async function viewAd(){ const r = await fetch(`${API}/view_ad?token=${token}`, {method:"POST"}); const j = await r.json(); if(j.detail) setMsg(j.detail); else { setMsg("Ad viewed +5"); fetchMe(token) } }
  return (<div style={{fontFamily:"Arial",padding:20}}><h1>PiPromise — We promise your work pays off.</h1><div><input placeholder="Your Pi username" value={piName} onChange={e=>setPiName(e.target.value)}/> <input placeholder="proof (wallet token/signature)" value={proof} onChange={e=>setProof(e.target.value)}/> <button onClick={connectPi}>Connect with Pi</button></div>{token && me && (<div><p>Connected as {me.pi_name} — Coins: {me.coins} — Flagged: {me.flagged ? "yes":"no"} — Blocked: {me.blocked ? "yes":"no"}</p><button onClick={mine}>Mine (100 coins / 12h)</button><button onClick={viewAd}>View Ad (+5 coins)</button></div>)}<p style={{color:"green"}}>{msg}</p><footer><small>Ensure PI_API_URL and PI_API_KEY are set in backend environment. Proof should be provided by Pi wallet.</small></footer></div>) }
createRoot(document.getElementById("root")).render(<App/>);