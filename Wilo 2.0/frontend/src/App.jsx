import { useCallback, useEffect, useMemo, useState } from "react";
import {
  formatApiError,
  getHealth,
  getOptions,
  postDatasetMatches,
  postPredict,
} from "./api.js";

const SPEEDS = [1450, 2900, 3000];

function Field({ label, hint, children }) {
  return (
    <label className="field">
      <span className="field-label">
        {label}
        {hint ? <span className="field-hint">{hint}</span> : null}
      </span>
      {children}
    </label>
  );
}

function Section({ icon, title, tint, children }) {
  return (
    <section className={`form-section tint-${tint}`}>
      <h3 className="section-title">
        <span className="section-icon" aria-hidden>
          {icon}
        </span>
        {title}
      </h3>
      <div className="section-grid">{children}</div>
    </section>
  );
}

export default function App() {
  const [health, setHealth] = useState(null);
  const [optionsLoading, setOptionsLoading] = useState(true);
  const [optionsError, setOptionsError] = useState(null);
  const [pumpTypes, setPumpTypes] = useState([]);
  const [impellerMocs, setImpellerMocs] = useState([]);
  const [diffuserMocs, setDiffuserMocs] = useState([]);
  const [specials, setSpecials] = useState([]);

  const [pumpType, setPumpType] = useState("");
  const [headPerChamber, setHeadPerChamber] = useState("");
  const [chambers, setChambers] = useState("");
  const [flow, setFlow] = useState("");
  const [totalHead, setTotalHead] = useState("");
  const [speed, setSpeed] = useState("");
  const [efficiency, setEfficiency] = useState("");
  const [pumpPower, setPumpPower] = useState("");
  const [special, setSpecial] = useState("NONE");

  const [impellerFirst, setImpellerFirst] = useState("");
  const [impellerConfirm, setImpellerConfirm] = useState("");
  const [impellerLocked, setImpellerLocked] = useState(false);

  const [diffuserFirst, setDiffuserFirst] = useState("");
  const [diffuserConfirm, setDiffuserConfirm] = useState("");
  const [diffuserLocked, setDiffuserLocked] = useState(false);

  const [mocError, setMocError] = useState(null);
  const [predictLoading, setPredictLoading] = useState(false);
  const [predictError, setPredictError] = useState(null);
  const [result, setResult] = useState(null);

  const [datasetLoading, setDatasetLoading] = useState(false);
  const [datasetError, setDatasetError] = useState(null);
  const [datasetRows, setDatasetRows] = useState(null);

  const refreshHealth = useCallback(async () => {
    const { ok, data } = await getHealth();
    if (ok) setHealth(data);
    else setHealth({ status: "error", model_message: formatApiError(data) });
  }, []);

  useEffect(() => {
    refreshHealth();
    const id = setInterval(refreshHealth, 30000);
    return () => clearInterval(id);
  }, [refreshHealth]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setOptionsLoading(true);
      setOptionsError(null);
      const { ok, data } = await getOptions();
      if (cancelled) return;
      if (!ok) {
        setOptionsError(formatApiError(data));
        setOptionsLoading(false);
        return;
      }
      const o = data.options || {};
      setPumpTypes(o.Pump_Type || []);
      setImpellerMocs(o.Impeller_MOC || []);
      setDiffuserMocs(o.Diffuser_MOC || []);
      setSpecials(o.Special_Instruction || []);
      setOptionsLoading(false);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const num = (v) => {
    const x = parseFloat(String(v).replace(",", "."));
    return Number.isFinite(x) ? x : NaN;
  };

  const validateMoc = useCallback(() => {
    if (!impellerLocked || !diffuserLocked) {
      setMocError("Confirm both Impeller and Diffuser MOC (select, lock, then match confirmation).");
      return false;
    }
    if (impellerFirst !== impellerConfirm) {
      setMocError("Impeller MOC confirmation does not match the first selection.");
      return false;
    }
    if (diffuserFirst !== diffuserConfirm) {
      setMocError("Diffuser MOC confirmation does not match the first selection.");
      return false;
    }
    setMocError(null);
    return true;
  }, [
    impellerLocked,
    diffuserLocked,
    impellerFirst,
    impellerConfirm,
    diffuserFirst,
    diffuserConfirm,
  ]);

  const buildPayload = useCallback(() => {
    const hpc = num(headPerChamber);
    const ch = num(chambers);
    const f = num(flow);
    const th = num(totalHead);
    const sp = num(speed);
    const eff = num(efficiency);
    const pp = pumpPower.trim() === "" ? null : num(pumpPower);
    return {
      pump_type: pumpType,
      impeller_moc: impellerFirst,
      impeller_moc_confirm: impellerConfirm,
      diffuser_moc: diffuserFirst,
      diffuser_moc_confirm: diffuserConfirm,
      special_instruction: special || "NONE",
      head_per_chamber: hpc,
      number_of_chambers: ch,
      speed_rpm: sp,
      flow_m3h: f,
      pump_efficiency: eff,
      total_head: th,
      pump_power_kw: pp,
    };
  }, [
    pumpType,
    impellerFirst,
    impellerConfirm,
    diffuserFirst,
    diffuserConfirm,
    special,
    headPerChamber,
    chambers,
    flow,
    totalHead,
    speed,
    efficiency,
    pumpPower,
  ]);

  const handlePredict = async (e) => {
    e.preventDefault();
    setPredictError(null);
    setResult(null);
    if (!validateMoc()) return;

    const p = buildPayload();
    const checks = [
      ["Pump type", p.pump_type],
      ["Head per chamber", p.head_per_chamber],
      ["Number of chambers", p.number_of_chambers],
      ["Flow", p.flow_m3h],
      ["Total head", p.total_head],
      ["Speed", p.speed_rpm],
      ["Efficiency", p.pump_efficiency],
    ];
    for (const [name, v] of checks) {
      if (v === "" || v === null || v === undefined || Number.isNaN(v)) {
        setPredictError(`Please enter a valid number for: ${name}.`);
        return;
      }
    }
    if (p.head_per_chamber <= 0 || p.number_of_chambers <= 0) {
      setPredictError("Head per chamber and chambers must be positive.");
      return;
    }
    if (p.pump_efficiency <= 0 || p.pump_efficiency > 100) {
      setPredictError("Efficiency must be between 0 and 100.");
      return;
    }

    setPredictLoading(true);
    try {
      const { ok, data } = await postPredict({
        ...p,
        pump_power_kw: p.pump_power_kw,
      });
      if (!ok) {
        setPredictError(formatApiError(data));
        return;
      }
      setResult(data);
    } catch (err) {
      setPredictError(err?.message || String(err));
    } finally {
      setPredictLoading(false);
    }
  };

  const handleDatasetLookup = async () => {
    setDatasetError(null);
    setDatasetRows(null);
    if (!validateMoc()) return;
    const p = buildPayload();
    if (
      Number.isNaN(p.head_per_chamber) ||
      Number.isNaN(p.flow_m3h) ||
      Number.isNaN(p.total_head)
    ) {
      setDatasetError("Fill numeric operating fields before searching the dataset.");
      return;
    }
    setDatasetLoading(true);
    try {
      const { ok, data } = await postDatasetMatches({
        pump_type: p.pump_type,
        impeller_moc: p.impeller_moc,
        diffuser_moc: p.diffuser_moc,
        special_instruction: p.special_instruction,
        head_per_chamber: p.head_per_chamber,
        number_of_chambers: p.number_of_chambers,
        speed_rpm: p.speed_rpm,
        flow_m3h: p.flow_m3h,
        pump_efficiency: p.pump_efficiency,
        total_head: p.total_head,
        pump_power_kw: p.pump_power_kw,
        match_mode: "close",
      });
      if (!ok) {
        setDatasetError(formatApiError(data));
        return;
      }
      setDatasetRows(data);
    } catch (err) {
      setDatasetError(err?.message || String(err));
    } finally {
      setDatasetLoading(false);
    }
  };

  const tableColumns = useMemo(() => {
    if (!datasetRows?.rows?.length) return [];
    return Object.keys(datasetRows.rows[0]);
  }, [datasetRows]);

  const healthBadge = () => {
    if (!health) return { text: "Checking API…", className: "badge neutral" };
    if (health.model_loaded) return { text: "Model ready", className: "badge ok" };
    return { text: "Model unavailable", className: "badge warn" };
  };
  const hb = healthBadge();

  return (
    <div className="page">
      <header className="hero">
        <div className="hero-inner">
          <p className="eyebrow">Wilo · ML-assisted design</p>
          <h1>Pump impeller diameter</h1>
          <p className="sub">
            Predict full and trimmed impeller diameters from your operating case. Material selections are
            confirmed twice before prediction.
          </p>
          <div className="hero-badges">
            <span className={hb.className}>{hb.text}</span>
            {health?.dataset_loaded ? (
              <span className="badge ok">Dataset loaded</span>
            ) : (
              <span className="badge neutral" title={health?.dataset_message || ""}>
                Dataset optional
              </span>
            )}
          </div>
        </div>
      </header>

      <main className="layout">
        <form className="card form-card" onSubmit={handlePredict}>
          <div className="card-head">
            <h2>Pump design inputs</h2>
            {optionsLoading ? (
              <p className="muted">Loading categories…</p>
            ) : optionsError ? (
              <p className="error-inline">{optionsError}</p>
            ) : null}
          </div>

          <Section icon="⚙" title="Configuration" tint="blue">
            <Field label="Pump type">
              <select
                value={pumpType}
                onChange={(e) => setPumpType(e.target.value)}
                required
                disabled={!!optionsError || pumpTypes.length === 0}
              >
                <option value="">Select pump type</option>
                {pumpTypes.map((x) => (
                  <option key={x} value={x}>
                    {x}
                  </option>
                ))}
              </select>
            </Field>
            <Field label="Chambers">
              <input
                type="number"
                min={1}
                step={1}
                value={chambers}
                onChange={(e) => setChambers(e.target.value)}
                placeholder="e.g. 10"
                required
              />
            </Field>
            <Field label="Head per chamber (m)">
              <input
                type="number"
                min={0}
                step="any"
                value={headPerChamber}
                onChange={(e) => setHeadPerChamber(e.target.value)}
                placeholder="m"
                required
              />
            </Field>
          </Section>

          <Section icon="◎" title="Operating conditions" tint="green">
            <Field label="Flow (m³/h)">
              <input
                type="number"
                min={0}
                step="any"
                value={flow}
                onChange={(e) => setFlow(e.target.value)}
                required
              />
            </Field>
            <Field label="Total head (m)">
              <input
                type="number"
                min={0}
                step="any"
                value={totalHead}
                onChange={(e) => setTotalHead(e.target.value)}
                required
              />
            </Field>
            <Field label="Speed (RPM)">
              <div className="speed-row">
                <input
                  type="number"
                  min={0}
                  step="any"
                  value={speed}
                  onChange={(e) => setSpeed(e.target.value)}
                  required
                />
                <div className="pill-group" role="group" aria-label="Common speeds">
                  {SPEEDS.map((s) => (
                    <button
                      key={s}
                      type="button"
                      className="pill"
                      onClick={() => setSpeed(String(s))}
                    >
                      {s}
                    </button>
                  ))}
                </div>
              </div>
            </Field>
            <Field label="Pump efficiency (%)">
              <input
                type="number"
                min={0}
                max={100}
                step="any"
                value={efficiency}
                onChange={(e) => setEfficiency(e.target.value)}
                required
              />
            </Field>
            <Field label="Pump power (kW)" hint="Optional — estimated from duty if empty">
              <input
                type="number"
                min={0}
                step="any"
                value={pumpPower}
                onChange={(e) => setPumpPower(e.target.value)}
                placeholder="Auto from flow, head, η if empty"
              />
            </Field>
          </Section>

          <Section icon="◆" title="Material of construction" tint="purple">
            <div className="moc-block full-span">
              <p className="moc-help">
                Select each material once, then <strong>confirm</strong> with a second matching selection.
                The first dropdown is hidden after you lock your choice.
              </p>

              <div className="moc-pair">
                <span className="moc-label">Impeller MOC</span>
                {!impellerLocked ? (
                  <select
                    value={impellerFirst}
                    onChange={(e) => {
                      const v = e.target.value;
                      setImpellerFirst(v);
                      setImpellerConfirm("");
                    }}
                    className="moc-first"
                  >
                    <option value="">Choose impeller material</option>
                    {impellerMocs.map((x) => (
                      <option key={x} value={x}>
                        {x}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="moc-locked">
                    <span className="moc-chip">{impellerFirst}</span>
                    <button
                      type="button"
                      className="linkish"
                      onClick={() => {
                        setImpellerLocked(false);
                        setImpellerConfirm("");
                      }}
                    >
                      Change
                    </button>
                  </div>
                )}
                {impellerFirst && !impellerLocked ? (
                  <button
                    type="button"
                    className="btn secondary small"
                    onClick={() => setImpellerLocked(true)}
                  >
                    Lock choice
                  </button>
                ) : null}
                {impellerLocked ? (
                  <select
                    value={impellerConfirm}
                    onChange={(e) => setImpellerConfirm(e.target.value)}
                    required
                    className={impellerConfirm && impellerConfirm !== impellerFirst ? "mismatch" : ""}
                  >
                    <option value="">Confirm impeller MOC (must match)</option>
                    {impellerMocs.map((x) => (
                      <option key={x} value={x}>
                        {x}
                      </option>
                    ))}
                  </select>
                ) : null}
              </div>

              <div className="moc-pair">
                <span className="moc-label">Diffuser MOC</span>
                {!diffuserLocked ? (
                  <select
                    value={diffuserFirst}
                    onChange={(e) => {
                      const v = e.target.value;
                      setDiffuserFirst(v);
                      setDiffuserConfirm("");
                    }}
                    className="moc-first"
                  >
                    <option value="">Choose diffuser material</option>
                    {diffuserMocs.map((x) => (
                      <option key={x} value={x}>
                        {x}
                      </option>
                    ))}
                  </select>
                ) : (
                  <div className="moc-locked">
                    <span className="moc-chip">{diffuserFirst}</span>
                    <button
                      type="button"
                      className="linkish"
                      onClick={() => {
                        setDiffuserLocked(false);
                        setDiffuserConfirm("");
                      }}
                    >
                      Change
                    </button>
                  </div>
                )}
                {diffuserFirst && !diffuserLocked ? (
                  <button
                    type="button"
                    className="btn secondary small"
                    onClick={() => setDiffuserLocked(true)}
                  >
                    Lock choice
                  </button>
                ) : null}
                {diffuserLocked ? (
                  <select
                    value={diffuserConfirm}
                    onChange={(e) => setDiffuserConfirm(e.target.value)}
                    required
                    className={
                      diffuserConfirm && diffuserConfirm !== diffuserFirst ? "mismatch" : ""
                    }
                  >
                    <option value="">Confirm diffuser MOC (must match)</option>
                    {diffuserMocs.map((x) => (
                      <option key={x} value={x}>
                        {x}
                      </option>
                    ))}
                  </select>
                ) : null}
              </div>
            </div>
          </Section>

          <Section icon="✦" title="Special instruction" tint="amber">
            <Field label="Special instruction" hint="Use NONE when not applicable">
              <select
                value={special}
                onChange={(e) => setSpecial(e.target.value)}
                disabled={specials.length === 0}
              >
                {specials.length === 0 ? (
                  <option value="NONE">NONE</option>
                ) : (
                  specials.map((x) => (
                    <option key={x} value={x}>
                      {x}
                    </option>
                  ))
                )}
              </select>
            </Field>
          </Section>

          {mocError ? <p className="form-error">{mocError}</p> : null}
          {predictError ? <p className="form-error">{predictError}</p> : null}

          <div className="form-actions">
            <button type="submit" className="btn primary" disabled={predictLoading || !!optionsError}>
              {predictLoading ? "Predicting…" : "Predict design"}
            </button>
          </div>
        </form>

        <aside className="card results-card">
          <h2>Predicted diameters</h2>
          {!result && !predictLoading ? (
            <p className="muted">
              Submit the form to see <strong>full</strong> and <strong>trimmed</strong> impeller diameters
              (mm).
            </p>
          ) : null}
          {predictLoading ? <p className="muted">Running pipeline…</p> : null}
          {result ? (
            <>
              <div className="result-hero">
                <div className="result-big">
                  <span className="result-label">Full diameter</span>
                  <span className="result-value">{result.full_diameter_mm.toFixed(2)} mm</span>
                </div>
                <div className="result-big secondary">
                  <span className="result-label">Trimmed diameter</span>
                  <span className="result-value">{result.trimmed_diameter_mm.toFixed(2)} mm</span>
                </div>
              </div>
              <div className="result-meta">
                <div>
                  <span className="meta-k">Pump power used</span>
                  <span className="meta-v">{result.pump_power_used_kw.toFixed(3)} kW</span>
                </div>
                {result.pump_power_was_estimated ? (
                  <p className="note">{result.message}</p>
                ) : null}
              </div>
            </>
          ) : null}

          <div className="dataset-block">
            <h3>Dataset reference</h3>
            <p className="muted small">
              Rows from <code>Impeller_Dataset.xlsx</code> that match your case (approximate numeric
              match). Requires the Excel file beside the API.
            </p>
            <button
              type="button"
              className="btn secondary"
              onClick={handleDatasetLookup}
              disabled={datasetLoading}
            >
              {datasetLoading ? "Searching…" : "Find matching rows"}
            </button>
            {datasetError ? <p className="form-error">{datasetError}</p> : null}
            {datasetRows ? (
              <>
                <p className="muted small">
                  {datasetRows.count} match{datasetRows.count === 1 ? "" : "es"}
                  {datasetRows.truncated ? " (showing first 200)" : ""}
                </p>
                {datasetRows.rows?.length ? (
                  <div className="table-wrap">
                    <table className="data-table">
                      <thead>
                        <tr>
                          {tableColumns.map((c) => (
                            <th key={c}>{c}</th>
                          ))}
                        </tr>
                      </thead>
                      <tbody>
                        {datasetRows.rows.map((row, i) => (
                          <tr key={i}>
                            {tableColumns.map((c) => (
                              <td key={c}>{row[c] == null ? "—" : String(row[c])}</td>
                            ))}
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <p className="muted">No matching rows for this input set.</p>
                )}
              </>
            ) : null}
          </div>
        </aside>
      </main>

      <footer className="footer">
        <p>
          Backend: FastAPI + scikit-learn pipeline · Frontend: React · Place{" "}
          <code>pump_pipeline_v3.pkl</code> and <code>model_config_v3.pkl</code> in{" "}
          <code>backend/models/</code>
        </p>
      </footer>
    </div>
  );
}
