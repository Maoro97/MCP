import type { Widget } from "@/lib/types";
import { DataTable } from "./DataTable";
import { RecordCard } from "./RecordCard";
import { KpiTiles } from "./KpiTiles";
import { MiniChart } from "./MiniChart";

/**
 * The "generative UI" dispatcher: given a structured widget from the assistant,
 * pick the right rich component. Adding a widget kind = one case here.
 */
export function WidgetRenderer({ widget }: { widget: Widget }) {
  switch (widget.kind) {
    case "table":
      return <DataTable widget={widget} />;
    case "record":
      return <RecordCard widget={widget} />;
    case "kpis":
      return <KpiTiles widget={widget} />;
    case "chart":
      return <MiniChart widget={widget} />;
    default:
      return null;
  }
}
