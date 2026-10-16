import { ShieldCheck, BrainCircuit, Database, AlertTriangle, Target, Layers, Lock } from "lucide-react";
import { PageHeader } from "../components/ui";

const FLOW = ["Labelled data", "Preprocessing", "Random Forest training", "Evaluation", "FastAPI prediction API", "React interface", "Transaction record & alert review"];

export default function About() {
  return <div>
    <PageHeader title="About Shoprite FraudGuard" subtitle="Smart Payment Security. Real-Time Fraud Risk Analysis."/>
    <div className="content-stack">
      <section className="panel"><h2><ShieldCheck size={19}/> Project overview</h2>
        <p className="muted-text">Shoprite FraudGuard is a university project that shows how a machine-learning model can estimate the risk that a payment transaction is fraudulent and how analysts can review flagged cases. It is an independent educational prototype. It is not an official Shoprite product, is not endorsed by Shoprite, and does not process real payments.</p></section>
      <section className="panel"><h2><Target size={19}/> Problem and objectives</h2>
        <p className="muted-text">Card fraud is rare but costly, and reviewing every payment by hand is impossible. The project aims to:</p>
        <ul><li>score each submitted transaction with a Random Forest model;</li><li>flag high-risk transactions as alerts instead of hiding them in a long list;</li>
          <li>let authorised analysts mark alerts as confirmed fraud or false positives, with notes;</li><li>show activity and risk over time from the stored records.</li></ul></section>
      <section className="panel"><h2><Layers size={19}/> How the system works</h2>
        <div className="hero-steps" aria-label="Workflow">{FLOW.map((s, i) => <span key={s}><span className="step">{s}</span>{i < FLOW.length - 1 && " →"}</span>)}</div>
        <ol><li>A payment form collects eight fields: amount, payment method, hour, failed attempts, new device, international flag, customer average spend and branch.</li>
          <li>The API checks your sign-in token, validates the fields and runs them through the saved model pipeline.</li>
          <li>The returned probability becomes a risk level (Low below 0.3, Medium 0.3–0.7, High 0.7 or more) and is saved.</li>
          <li>Transactions above the model's threshold become alerts for review.</li></ol></section>
      <section className="panel"><h2><BrainCircuit size={19}/> Machine-learning approach and data</h2>
        <ul><li><strong>Model:</strong> scikit-learn Random Forest with class weighting for rare fraud, trained on a stratified 80/20 split and evaluated on the held-out part (precision, recall, F1, PR-AUC, ROC-AUC, confusion matrix).</li>
          <li><strong>Payment-form model:</strong> trained on <em>synthetic</em> data whose fraud labels come from a rule-based formula. It demonstrates the pipeline; its scores do not show real-world accuracy.</li>
          <li><strong>PCA Model Demo:</strong> a separate model for the public Kaggle credit-card dataset (anonymised European card transactions, features V1–V28). Those features cannot be produced from the payment form, so the demo takes rows from the dataset itself.</li>
          <li><strong>Real Shoprite data:</strong> none is used.</li>
          <li>A prediction is a risk estimate. It is <strong>not proof of fraud</strong>.</li></ul></section>
      <section className="panel"><h2><Database size={19}/> Technology stack</h2>
        <ul><li>Frontend: React, Vite, React Router, Recharts, Lucide icons.</li><li>Backend: Python, FastAPI, scikit-learn, pandas.</li>
          <li>Sign-in: Supabase Auth, verified again by the API. Storage: SQLite locally, optionally Supabase Postgres with Row Level Security.</li></ul></section>
      <section className="panel"><h2><Lock size={19}/> Security and privacy</h2>
        <p className="muted-text">No card numbers, CVVs, PINs or passwords are collected. Customers see only their own transactions; analysts and admins can review all alerts. The project has not been security-certified and is not PCI DSS compliant.</p></section>
      <section className="panel"><h2><AlertTriangle size={19}/> Disclaimer</h2>
        <p className="muted-text">For learning and demonstration only. Do not use it to approve, decline or investigate real payments.</p></section>
    </div></div>;
}
