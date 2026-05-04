import { NodeLabel } from '../core/graph/types';

// Node colors by type - slightly muted for less visual noise
export const NODE_COLORS: Record<NodeLabel, string> = {
  Project: '#ffffff',    // Purple - prominent
  Package: '#d4d4d4',    // Violet
  Module: '#e5e5e5',     // Violet darker
  Folder: '#404040',     // Indigo
  File: '#e5e5e5',       // Blue
  Class: '#ffffff',      // Amber - stands out
  Function: '#d4d4d4',   // Emerald
  Method: '#e5e5e5',     // Teal
  Variable: '#e5e5e5',   // Slate - muted (less important)
  Interface: '#d4d4d4',  // Pink
  Enum: '#ffffff',       // Orange
  Decorator: '#ffffff',  // Yellow
  Import: '#404040',     // Slate darker - very muted
  Type: '#ffffff',       // Violet light
  CodeElement: '#e5e5e5', // Slate - muted
  Community: '#e5e5e5',  // Indigo light - cluster indicator
  Process: '#ffffff',    // Rose - execution flow indicator
};

// Node sizes by type - clear visual hierarchy with dramatic size differences
// Structural nodes are MUCH larger to make hierarchy obvious
export const NODE_SIZES: Record<NodeLabel, number> = {
  Project: 20,     // Largest - root of everything
  Package: 16,     // Major structural element
  Module: 13,      // Important container
  Folder: 10,      // Structural - clearly bigger than files
  File: 6,         // Common element - smaller than folders
  Class: 8,        // Important code structure
  Function: 4,     // Common code element - small
  Method: 3,       // Smaller than function
  Variable: 2,     // Tiny - leaf node
  Interface: 7,    // Important type definition
  Enum: 5,         // Type definition
  Decorator: 2,    // Tiny modifier
  Import: 1.5,     // Very small - usually hidden anyway
  Type: 3,         // Type alias - small
  CodeElement: 2,  // Generic small
  Community: 0,    // Hidden by default - metadata node
  Process: 0,      // Hidden by default - metadata node
};

// Community color palette for cluster-based coloring
export const COMMUNITY_COLORS = [
  '#ffffff', // red
  '#d4d4d4', // orange
  '#e5e5e5', // yellow
  '#404040', // green
  '#e5e5e5', // cyan
  '#d4d4d4', // blue
  '#ffffff', // violet
  '#404040', // fuchsia
  '#e5e5e5', // pink
  '#d4d4d4', // rose
  '#ffffff', // teal
  '#e5e5e5', // lime
];

export const getCommunityColor = (communityIndex: number): string => {
  return COMMUNITY_COLORS[communityIndex % COMMUNITY_COLORS.length];
};

// Labels to show by default (hide imports and variables by default as they clutter)
export const DEFAULT_VISIBLE_LABELS: NodeLabel[] = [
  'Project',
  'Package',
  'Module',
  'Folder',
  'File',
  'Class',
  'Function',
  'Method',
  'Interface',
  'Enum',
  'Type',
];

// All filterable labels
export const FILTERABLE_LABELS: NodeLabel[] = [
  'Folder',
  'File',
  'Class',
  'Function',
  'Method',
  'Variable',
  'Interface',
  'Import',
];

// Edge/Relation types
export type EdgeType = 'CONTAINS' | 'DEFINES' | 'IMPORTS' | 'CALLS' | 'EXTENDS' | 'IMPLEMENTS';

export const ALL_EDGE_TYPES: EdgeType[] = [
  'CONTAINS',
  'DEFINES',
  'IMPORTS',
  'CALLS',
  'EXTENDS',
  'IMPLEMENTS',
];

// Default visible edges (CALLS hidden by default to reduce clutter)
export const DEFAULT_VISIBLE_EDGES: EdgeType[] = [
  'CONTAINS',
  'DEFINES',
  'IMPORTS',
  'EXTENDS',
  'IMPLEMENTS',
  'CALLS',
];

// Edge display info for UI
export const EDGE_INFO: Record<EdgeType, { color: string; label: string }> = {
  CONTAINS: { color: '#404040', label: 'Contains' },
  DEFINES: { color: '#e5e5e5', label: 'Defines' },
  IMPORTS: { color: '#d4d4d4', label: 'Imports' },
  CALLS: { color: '#ffffff', label: 'Calls' },
  EXTENDS: { color: '#e5e5e5', label: 'Extends' },
  IMPLEMENTS: { color: '#d4d4d4', label: 'Implements' },
};
