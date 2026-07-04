// membership.js — shared plan helpers + live sync across tabs
// Used by: dashboard.html, membership.html, payment.html

const API_BASE = "http://127.0.0.1:8000";

const PLAN_INFO = {
    "Weekly Access":  { price: 50,   days: 7,   cycle: "Per Week",  short: "Weekly"  },
    "Monthly Access": { price: 150,  days: 30,  cycle: "Per Month", short: "Monthly" },
    "Yearly Access":  { price: 1500, days: 365, cycle: "Per Year",  short: "Yearly"  },
    "FREE":           { price: 0,    days: 0,   cycle: "—",         short: "Free"    }
};

function getPlanInfo(plan){
    return PLAN_INFO[plan] || PLAN_INFO["FREE"];
}

function daysRemaining(plan, startedIso){
    const info = getPlanInfo(plan);
    if(!startedIso || plan === "FREE") return info.days;
    const started    = new Date(startedIso);
    const elapsedDays = Math.floor((Date.now() - started.getTime()) / 86400000);
    return Math.max(info.days - elapsedDays, 0);
}

// ── fetch profile from backend & cache in localStorage ──────────────
async function fetchProfile(){
    const token = localStorage.getItem("token");
    if(!token) return null;

    try{
        const res  = await fetch(`${API_BASE}/profile`, {
            headers: { "Authorization": `Bearer ${token}` }
        });
        const data = await res.json();

        if(data && data.plan){
            localStorage.setItem("plan",         data.plan);
            localStorage.setItem("plan_started", data.plan_started || "");
            localStorage.setItem("full_name",    data.full_name    || "");
        }
        return data;
    } catch {
        // Backend unreachable — fall back to last cached values
        return {
            plan:         localStorage.getItem("plan")         || "FREE",
            plan_started: localStorage.getItem("plan_started") || null,
            full_name:    localStorage.getItem("full_name")    || "User"
        };
    }
}

// ── broadcast plan change to ALL open tabs (dashboard, etc.) ────────
// Called right after a successful payment so dashboard updates live.
function broadcastPlanUpdate(plan, planStarted){
    // 1. Write to localStorage so same-origin tabs get a "storage" event
    localStorage.setItem("plan",         plan);
    localStorage.setItem("plan_started", planStarted || "");

    // 2. BroadcastChannel for same-tab / same-window listeners
    try {
        const ch = new BroadcastChannel("nexus_plan_update");
        ch.postMessage({ plan, plan_started: planStarted });
        ch.close();
    } catch(_) {}
}

// ── render the membership status card ───────────────────────────────
// ids = { planName, price, days, badge }
function renderMembershipStatus(data, ids){
    const plan      = (data && data.plan) || "FREE";
    const info      = getPlanInfo(plan);
    const isActive  = plan !== "FREE";
    const remaining = daysRemaining(plan, data && data.plan_started);

    const planNameEl = document.getElementById(ids.planName);
    const priceEl    = document.getElementById(ids.price);
    const daysEl     = document.getElementById(ids.days);
    const badgeEl    = document.getElementById(ids.badge);

    if(planNameEl) planNameEl.innerText = isActive ? `${plan} — Active` : "No Active Plan";
    if(priceEl)    priceEl.innerText    = isActive ? `₹${info.price} ${info.cycle}` : "₹0";
    if(daysEl)     daysEl.innerText     = isActive ? `${remaining}` : "0";
    if(badgeEl){
        badgeEl.innerText   = isActive ? "Active" : "Free";
        badgeEl.className   = "badge " + (isActive ? "badge-green" : "badge-teal");
    }

    return { plan, info, isActive, remaining };
}

// ── listen for plan updates from other tabs / same-page broadcast ───
// Pages that show plan info call this once on load.
function listenForPlanUpdates(onUpdate){
    // BroadcastChannel (same origin, any tab)
    try {
        const ch = new BroadcastChannel("nexus_plan_update");
        ch.onmessage = (e) => onUpdate(e.data);
    } catch(_) {}

    // storage event (cross-tab fallback)
    window.addEventListener("storage", (e) => {
        if(e.key === "plan" || e.key === "plan_started"){
            onUpdate({
                plan:         localStorage.getItem("plan")         || "FREE",
                plan_started: localStorage.getItem("plan_started") || null
            });
        }
    });
}
