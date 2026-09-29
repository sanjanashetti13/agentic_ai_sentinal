import type { FormEvent } from "react";
import { useState } from "react";
import { createMonitor, updateMonitor } from "../api/monitors";
import type { Monitor } from "../types";
import { DEMO_GOAL, DEMO_URL, validateMonitorInput } from "../utils/format";

type CreateMonitorFormProps = {
  onCreated: (monitor: Monitor) => void;
  onCancel: () => void;
};

export function CreateMonitorForm({
  onCreated,
  onCancel,
}: CreateMonitorFormProps) {
  const [goal, setGoal] = useState("");
  const [url, setUrl] = useState("");
  const [enabled, setEnabled] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    const validation = validateMonitorInput(goal, url);
    if (validation) {
      setError(validation);
      return;
    }
    setError(null);
    setSaving(true);
    try {
      let created = await createMonitor({
        goal: goal.trim(),
        url: url.trim(),
      });
      if (!enabled) {
        created = await updateMonitor(created.id, { enabled: false });
      }
      setGoal("");
      setUrl("");
      setEnabled(true);
      onCreated(created);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create monitor.");
    } finally {
      setSaving(false);
    }
  }

  return (
    <form className="form-card" onSubmit={handleSubmit}>
      <label htmlFor="goal">Monitoring goal</label>
      <textarea
        id="goal"
        rows={2}
        value={goal}
        onChange={(event) => setGoal(event.target.value)}
        placeholder={DEMO_GOAL}
        required
      />

      <label htmlFor="url">Source URL</label>
      <input
        id="url"
        type="url"
        value={url}
        onChange={(event) => setUrl(event.target.value)}
        placeholder={DEMO_URL}
        required
      />

      <label className="form-check">
        <input
          type="checkbox"
          checked={enabled}
          onChange={(event) => setEnabled(event.target.checked)}
        />
        Enabled
      </label>

      {error ? <p className="error">{error}</p> : null}

      <div className="actions">
        <button className="primary" type="submit" disabled={saving}>
          {saving ? "Creating..." : "Create Monitor"}
        </button>
        <button
          className="secondary"
          type="button"
          onClick={() => {
            setGoal(DEMO_GOAL);
            setUrl(DEMO_URL);
            setEnabled(true);
            setError(null);
          }}
        >
          Use demo values
        </button>
        <button className="secondary" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  );
}
