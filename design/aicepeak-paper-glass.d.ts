// Aicepeak Paper & Glass — window.AicepeakPaperGlass (React 18, classic script).
import type { ReactNode, CSSProperties, MouseEventHandler } from 'react';

export type IconName = 'documents' | 'positions' | 'topics' | 'bell' | 'chat' | 'search' | 'close' | 'send' | 'status' | 'check' | 'link' | 'arrow' | 'plus' | 'chevron' | 'sign-out';

export interface IconProps { name: IconName; size?: number; className?: string; style?: CSSProperties }

/** standard: the default glass. airy: brighter, more translucent glass with white, borderless controls in light; identical to standard in dark. */
export type GlassStyle = 'standard' | 'airy';

export interface GlassBarNavItem { label: string; icon?: IconName; href?: string; current?: boolean; onClick?: MouseEventHandler }
export interface GlassBarProps {
  /** Logo image URL (the Aicepeak mark). */
  logoSrc?: string;
  logoAlt?: string;
  /** Exactly three items; one has `current`. */
  nav: GlassBarNavItem[];
  /** The last crumb is the current page. */
  breadcrumbs?: { label: string; href?: string }[];
  /** Glass Buttons / IconButtons on the right. */
  actions?: ReactNode;
  /** Glass style, default standard. Use the same style for the bar and the assistant. */
  glass?: GlassStyle;
  className?: string;
  style?: CSSProperties;
}

export interface AssistantPanelProps {
  title?: string;
  /** Context line under the title, e.g. "Kontext · Positionen · Alpine Paper 2027". */
  context?: string;
  /** Messages: AssistantMessage, UserMessage. */
  children?: ReactNode;
  /** Up to three suggestion chips above the composer. */
  suggestions?: string[];
  onSuggestion?: (text: string) => void;
  placeholder?: string;
  onSend?: (text: string) => void;
  /** Pass null to hide the close button. */
  onClose?: MouseEventHandler | null;
  /** Glass style, default standard. */
  glass?: GlassStyle;
  /** Rolled-up mode: the header becomes a toggle with a chevron; collapsed, the panel is a bar of bar-height. */
  collapsible?: boolean;
  /** With `collapsible`: open or rolled up. Give the panel its open height via `style` (e.g. calc(100% - 32px)). */
  expanded?: boolean;
  onToggle?: MouseEventHandler;
  inputId?: string;
  className?: string;
  style?: CSSProperties;
}
export interface AssistantMessageProps { children?: ReactNode; /** e.g. "Quellen · 6 Artikel · 3 Themen" */ sources?: string }
export interface UserMessageProps { children?: ReactNode }
export interface AssistantItemProps { label: string; note?: string; href?: string; onClick?: MouseEventHandler }

export interface ButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  /** glass: inside glass only · review: resolves open questions · paper: any other paper action. Default glass. */
  variant?: 'glass' | 'review' | 'paper';
  /** Trailing icon. */
  icon?: IconName;
  /** Leading signal dot (glass only, e.g. the Chat toggle). */
  dot?: boolean;
  children?: ReactNode;
}
export interface IconButtonProps extends Omit<React.ButtonHTMLAttributes<HTMLButtonElement>, 'children'> {
  icon: IconName;
  /** Required: becomes aria-label and title. */
  label: string;
  /** glass (default) or a square paper button. */
  surface?: 'glass' | 'paper';
  size?: number;
}

export interface PageHeaderProps {
  eyebrow?: string;
  /** Title without the closing full stop: it is added in `signal`. */
  title: ReactNode;
  meta?: string;
  status?: string;
  /** Hide the review icon in front of the status. */
  statusIcon?: boolean;
  /** Usually a Button variant="review". */
  action?: ReactNode;
  className?: string;
}

export interface TabsProps {
  items: { label: string; count?: number | string; selected?: boolean }[];
  onSelect?: (index: number, item: TabsProps['items'][number]) => void;
  label?: string;
}

export interface KpiStripProps {
  base: { label: string; value: number | string };
  signal: { label: string; value: number | string; delta?: number | string; unit?: string };
  /** The signal band runs to the right screen edge (default true). */
  bleed?: boolean;
}

export interface DataTableColumn {
  key: string;
  label: ReactNode;
  sub?: ReactNode;
  /** Right-aligned, tabular. */
  numeric?: boolean;
  /** paper-column background and semibold: Ist and Forecast only. */
  highlight?: boolean;
  /** Grid track, default "minmax(84px, 1fr)". */
  width?: string;
}
export interface DataTableProps {
  id?: string;
  title?: string;
  description?: string;
  /** e.g. "T€ · gerundet". */
  unit?: string;
  /** Pass null to hide the search button. */
  onSearch?: MouseEventHandler | null;
  searchLabel?: string;
  columns: DataTableColumn[];
  rows: { key?: string; selected?: boolean; onClick?: MouseEventHandler; cells: Record<string, ReactNode> }[];
  total?: { cells: Record<string, ReactNode> };
  minWidth?: number;
  /** Search in the table head: replaces the title row with a large search field. */
  search?: {
    placeholder?: string;
    /** Accessible label, also the table's name. */
    label?: string;
    /** Mono hint on the right, e.g. "Name, Jahr oder Zeitraum". */
    hint?: string;
    /** Result count on the far right, e.g. "8 Projekte". */
    count?: ReactNode;
    value?: string;
    onChange?: (value: string) => void;
  };
}

export interface LineItemNameProps { children: ReactNode; href?: string; onClick?: MouseEventHandler }
export interface DeltaProps { value: number }
export interface TopicsLinkProps { topics: string[]; href?: string; onClick?: MouseEventHandler }
export interface DotMatrixProps {
  /** One value per column (Ist 2025, Ist 2026, Basis 2027, Forecast 2027). */
  values: number[];
  /** Columns = rows, 3–6. Default: number of values (4). */
  size?: number;
  /** Accessible description with all values. */
  label?: string;
}
/** review: open question (outlined) · done: verified (check) · running: an import or extraction in progress (signal dot). */
export interface StatusTagProps { status: 'review' | 'done' | 'running'; children?: ReactNode }

export interface ProjectMarkProps {
  /** Stable project ID: decides the shape, never changes. */
  id: string;
  /** EBITDA result in T€: its size sets how many dots are full, its sign the colour. */
  value: number;
  /** Accessible description; default "EBITDA-Ergebnis <value> T€". */
  label?: string;
  /** Drawn on a signal fill (set by ProjectTile when highlighted). */
  onSignal?: boolean;
  className?: string;
}

export interface ProjectTilesProps { /** Usually three ProjectTile; the first is highlighted. */ children?: ReactNode }
export interface ProjectTileProps {
  /** Mono time line, e.g. "Vor 20 Min.". */
  opened?: string;
  title: string;
  /** Where the user left off, e.g. "Zuletzt bei Materialaufwand". */
  note?: string;
  status?: StatusTagProps['status'];
  statusText?: string;
  /** Figure on the right, e.g. 6616 or "56 %". */
  value?: number | string;
  unit?: string;
  /** Project mark props; omit for no mark. */
  mark?: Pick<ProjectMarkProps, 'id' | 'value' | 'label'>;
  /** The most recent project: signal fill. One per row. */
  highlight?: boolean;
  href?: string;
  onClick?: MouseEventHandler;
}

export interface SignInCardProps {
  logoSrc?: string;
  logoAlt?: string;
  /** Without the full stop; default "Anmelden". */
  title?: string;
  /** Default "Mit Microsoft anmelden". */
  buttonLabel?: string;
  /** Shows busyLabel and ignores further submits. */
  busy?: boolean;
  /** Default "Anmeldung läuft …". */
  busyLabel?: string;
  onSignIn?: (e: React.FormEvent) => void;
  /** Small line under the button, e.g. who grants access. */
  note?: string;
  className?: string;
  style?: CSSProperties;
}

export declare function GlassBar(props: GlassBarProps): JSX.Element;
export declare function AssistantPanel(props: AssistantPanelProps): JSX.Element;
export declare function AssistantMessage(props: AssistantMessageProps): JSX.Element;
export declare function UserMessage(props: UserMessageProps): JSX.Element;
export declare function AssistantItem(props: AssistantItemProps): JSX.Element;
export declare function Button(props: ButtonProps): JSX.Element;
export declare function IconButton(props: IconButtonProps): JSX.Element;
export declare function PageHeader(props: PageHeaderProps): JSX.Element;
export declare function Tabs(props: TabsProps): JSX.Element;
export declare function KpiStrip(props: KpiStripProps): JSX.Element;
export declare function DataTable(props: DataTableProps): JSX.Element;
export declare function LineItemName(props: LineItemNameProps): JSX.Element;
export declare function Delta(props: DeltaProps): JSX.Element;
export declare function TopicsLink(props: TopicsLinkProps): JSX.Element;
export declare function DotMatrix(props: DotMatrixProps): JSX.Element;
export declare function StatusTag(props: StatusTagProps): JSX.Element;
export declare function ProjectMark(props: ProjectMarkProps): JSX.Element;
export declare function ProjectTiles(props: ProjectTilesProps): JSX.Element;
export declare function ProjectTile(props: ProjectTileProps): JSX.Element;
export declare function SignInCard(props: SignInCardProps): JSX.Element;
export declare function Icon(props: IconProps): JSX.Element | null;
/** 42800 → "42 800", −14400 → "−14 400". */
export declare function formatNumber(n: number): string;
/** 640 → "+640", 0 → "±0". */
export declare function formatDelta(n: number): string;
