import { humanLoopDescription, humanLoopLabel } from "../utils/format";

export function HumanLoopNotice({
  state,
}: {
  state: string | null | undefined;
}) {
  const description = humanLoopDescription(state);
  if (!state || state === "no_action" || !description) {
    return null;
  }
  return (
    <p className="hitl-line">
      Human-in-loop: {humanLoopLabel(state)}. {description}
    </p>
  );
}
