// Small stroke icons (24px grid, drawn at 16px by default) so every search result type is recognisable.

type P = { size?: number; className?: string };

function Svg({ size = 16, className, children }: P & { children: React.ReactNode }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
      strokeLinecap="round" strokeLinejoin="round" className={className} aria-hidden="true">
      {children}
    </svg>
  );
}

export const SearchIcon = (p: P) => <Svg {...p}><circle cx="11" cy="11" r="7" /><path d="m20 20-3.5-3.5" /></Svg>;
export const CloseIcon = (p: P) => <Svg {...p}><path d="M18 6 6 18M6 6l12 12" /></Svg>;
export const ProgramIcon = (p: P) => <Svg {...p}><path d="m8 9-4 3 4 3M16 9l4 3-4 3M13.5 6l-3 12" /></Svg>;
export const MenuIcon = (p: P) => <Svg {...p}><path d="M4 6h16M4 12h16M4 18h10" /></Svg>;
export const FieldIcon = (p: P) => <Svg {...p}><rect x="3" y="5" width="18" height="14" rx="2" /><path d="M3 10h18M9 10v9" /></Svg>;
export const DictIcon = (p: P) => <Svg {...p}><path d="M5 4h11a3 3 0 0 1 3 3v13H8a3 3 0 0 1-3-3z" /><path d="M5 17a3 3 0 0 1 3-3h11" /></Svg>;
export const FactIcon = (p: P) => <Svg {...p}><path d="M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3z" /></Svg>;
export const CodeIcon = (p: P) => <Svg {...p}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M9 14h6M9 17h4" /></Svg>;
export const ArrowIcon = (p: P) => <Svg {...p}><path d="M5 12h14M13 6l6 6-6 6" /></Svg>;

export const HomeIcon = (p: P) => <Svg {...p}><path d="M3 11.5 12 4l9 7.5M5.5 9.5V20h13V9.5" /></Svg>;
export const ChatIcon = (p: P) => <Svg {...p}><path d="M21 12a8 8 0 0 1-11.6 7.1L4 20l1-4.6A8 8 0 1 1 21 12z" /></Svg>;
export const FlowIcon = (p: P) => <Svg {...p}><rect x="3" y="3" width="7" height="5" rx="1.5" /><rect x="14" y="16" width="7" height="5" rx="1.5" /><path d="M6.5 8v5a3 3 0 0 0 3 3h4.5" /></Svg>;
export const FilesIcon = (p: P) => <Svg {...p}><ellipse cx="12" cy="6" rx="8" ry="3" /><path d="M4 6v6c0 1.7 3.6 3 8 3s8-1.3 8-3V6M4 12v6c0 1.7 3.6 3 8 3s8-1.3 8-3v-6" /></Svg>;
export const SyncIcon = (p: P) => <Svg {...p}><path d="M20 11a8 8 0 0 0-14.3-4.9L4 8M4 4v4h4M4 13a8 8 0 0 0 14.3 4.9L20 16M20 20v-4h-4" /></Svg>;
export const SparkIcon = (p: P) => <Svg {...p}><path d="M12 3v4M12 17v4M3 12h4M17 12h4M6.3 6.3l2.5 2.5M15.2 15.2l2.5 2.5M6.3 17.7l2.5-2.5M15.2 8.8l2.5-2.5" /></Svg>;
export const CopyIcon = (p: P) => <Svg {...p}><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M5 15V5a2 2 0 0 1 2-2h8" /></Svg>;
export const CheckIcon = (p: P) => <Svg {...p}><path d="M5 12.5 10 17 19 7" /></Svg>;
export const AlertIcon = (p: P) => <Svg {...p}><path d="M12 3 2 20h20L12 3zM12 10v4M12 17.5v.5" /></Svg>;
export const GitIcon = (p: P) => <Svg {...p}><circle cx="6" cy="6" r="2.5" /><circle cx="6" cy="18" r="2.5" /><circle cx="18" cy="9" r="2.5" /><path d="M6 8.5v7M18 11.5c0 3-3 3.5-6 3.5H8.5" /></Svg>;
export const ThumbUpIcon = (p: P) => <Svg {...p}><path d="M7 11v9H4v-9zM7 11l4-8c1.7 0 2.5 1 2.5 2.5V9H19a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 17.8 20H7" /></Svg>;
export const ThumbDownIcon = (p: P) => <Svg {...p}><path d="M17 13V4h3v9zM17 13l-4 8c-1.7 0-2.5-1-2.5-2.5V15H5a2 2 0 0 1-2-2.3l1.2-7A2 2 0 0 1 6.2 4H17" /></Svg>;
export const SendIcon = (p: P) => <Svg {...p}><path d="M12 19V5M5 12l7-7 7 7" /></Svg>;
export const TrashIcon = (p: P) => <Svg {...p}><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3" /></Svg>;
export const PlusIcon = (p: P) => <Svg {...p}><path d="M12 5v14M5 12h14" /></Svg>;
export const ChevronIcon = (p: P) => <Svg {...p}><path d="m9 6 6 6-6 6" /></Svg>;

export const CompareIcon = (p: P) => <Svg {...p}><path d="M8 3 4 7l4 4M4 7h11M16 21l4-4-4-4M20 17H9" /></Svg>;
export const NoteIcon = (p: P) => <Svg {...p}><path d="M5 4h14v11l-5 5H5z" /><path d="M14 20v-5h5M8 9h8M8 13h4" /></Svg>;
export const SettingsIcon = (p: P) => <Svg {...p}><circle cx="12" cy="12" r="3" /><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z" /></Svg>;
export const ExportIcon = (p: P) => <Svg {...p}><path d="M12 15V3M7 8l5-5 5 5" /><path d="M5 13v6a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-6" /></Svg>;
export const DownloadIcon = (p: P) => <Svg {...p}><path d="M12 3v12M7 10l5 5 5-5" /><path d="M5 17v2a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-2" /></Svg>;
export const PanelIcon = (p: P) => <Svg {...p}><rect x="3" y="4" width="18" height="16" rx="2" /><path d="M9 4v16" /></Svg>;
export const ScreenIcon = (p: P) => <Svg {...p}><rect x="3" y="4" width="18" height="13" rx="2" /><path d="M3 8h18M8 21h8M12 17v4" /></Svg>;
export const ClockIcon = (p: P) => <Svg {...p}><circle cx="12" cy="12" r="9" /><path d="M12 7v5l3 2" /></Svg>;
export const NetworkIcon = (p: P) => <Svg {...p}><circle cx="5" cy="17" r="2.2" /><circle cx="19" cy="17" r="2.2" /><circle cx="12" cy="5.5" r="2.2" /><path d="M6.6 15.4 10.6 7.4M13.4 7.4l4 8M7.3 17.5c3 1.5 6.4 1.5 9.4 0" /></Svg>;
export const ProcessIcon = (p: P) => <Svg {...p}><rect x="2.5" y="8" width="5" height="8" rx="1.5" /><rect x="9.5" y="8" width="5" height="8" rx="1.5" /><rect x="16.5" y="8" width="5" height="8" rx="1.5" /><path d="M7.5 12h2M14.5 12h2" /></Svg>;
export const ReportIcon = (p: P) => <Svg {...p}><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" /><path d="M14 3v6h6M8 17v-3M12 17v-6M16 17v-2" /></Svg>;
export const LinkIcon = (p: P) => <Svg {...p}><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1" /><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1" /></Svg>;
export const EditIcon = (p: P) => <Svg {...p}><path d="M4 20h4L19 9l-4-4L4 16z" /><path d="m13.5 6.5 4 4" /></Svg>;

export const KIND_ICON: Record<string, (p: P) => React.JSX.Element> = {
  Program: ProgramIcon, Menu: MenuIcon, Field: FieldIcon, "DICT name": DictIcon, Fact: FactIcon, Code: CodeIcon,
  "By meaning": SparkIcon,
};
export const UsersIcon = (p: P) => <Svg {...p}><circle cx="9" cy="8" r="3.5" /><path d="M2.5 20a6.5 6.5 0 0 1 13 0M16 4.6a3.5 3.5 0 0 1 0 6.8M18 14.2a6.5 6.5 0 0 1 3.5 5.8" /></Svg>;
export const LogoutIcon = (p: P) => <Svg {...p}><path d="M15 4h3a2 2 0 0 1 2 2v12a2 2 0 0 1-2 2h-3M10 17l-5-5 5-5M5 12h11" /></Svg>;
export const BridgeIcon = (p: P) => <Svg {...p}><path d="M3 18V9M21 18V9M3 9c3 0 6 2 9 2s6-2 9-2M3 14h18M8 14v-3.6M16 14v-3.6M12 14v-3" /></Svg>;
