// Tell TypeScript to treat CSS imports as valid modules
// This fixes: "Cannot find module or type declarations for side-effect import"
declare module "*.css" {
  const content: Record<string, string>;
  export default content;
}

// Tell TypeScript to treat SVG imports as React components
declare module "*.svg" {
  import type { FunctionComponent, SVGProps } from "react";
  const ReactComponent: FunctionComponent<SVGProps<SVGSVGElement>>;
  export default ReactComponent;
}

// Tell TypeScript to treat image imports as strings
declare module "*.png" { const src: string; export default src; }
declare module "*.jpg" { const src: string; export default src; }
declare module "*.jpeg"{ const src: string; export default src; }
declare module "*.webp"{ const src: string; export default src; }