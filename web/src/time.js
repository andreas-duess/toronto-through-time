import { LayerExtension } from "@deck.gl/core";

// Shows each object from its first year to its last. Buildings ("rise") grow out of the ground,
// carry a tint while they are new and sink in their last year; flat things ("fade") fade in.
const uniforms = `layout(std140) uniform epochUniforms {
  vec4 tint;
  float year;
  float growYears;
  float tintYears;
} epoch;
`;
const epochModule = {
  name: "epoch",
  vs: uniforms,
  uniformTypes: { tint: "vec4<f32>", year: "f32", growYears: "f32", tintYears: "f32" },
};

export class TimeExtension extends LayerExtension {
  static extensionName = "TimeExtension";
  static defaultProps = {
    // [first year, last year, 1 to appear at once, 1 to vanish at once]: the last two are for an
    // object that takes over from another one or hands over to one
    getYears: { type: "accessor", value: [0, 9999, 0, 0] },
    currentYear: 2026,
    growYears: 1.5,
    // colour multiplier for a new object, back to 1 after tintYears
    tint: [1, 1, 1],
    tintYears: 1,
  };

  getShaders(extension) {
    const inject = {
      "vs:#decl": "in vec4 epochYears;\nfloat epoch_age;\nfloat epoch_grow;\n",
      "vs:#main-start": `
        epoch_age = epoch.year - epochYears.x;
        epoch_grow = max(epochYears.z, smoothstep(0.0, epoch.growYears, epoch_age))
          * max(epochYears.w, smoothstep(0.0, 0.7, epochYears.y - epoch.year));
      `,
      "vs:#main-end": "if (epoch_age < 0.0 || epoch.year >= epochYears.y) gl_Position = vec4(0.0);\n",
    };
    if (extension.opts.mode === "rise") {
      inject["vs:DECKGL_FILTER_GL_POSITION"] = `
        vec4 epochPos = geometry.position;
        float epochBase = project_size(geometry.worldPosition.z);
        epochPos.z = epochBase + (epochPos.z - epochBase) * max(epoch_grow, 0.02);
        position = project_common_position_to_clipspace(epochPos);
      `;
      inject["vs:DECKGL_FILTER_COLOR"] = `
        color.rgb *= mix(epoch.tint.rgb, vec3(1.0), max(epochYears.z, smoothstep(epoch.growYears, epoch.tintYears, epoch_age)));
      `;
    } else {
      inject["vs:DECKGL_FILTER_COLOR"] = "color.a *= epoch_grow;\n";
    }
    return { modules: [epochModule], inject };
  }

  initializeState() {
    this.getAttributeManager()?.add({
      epochYears: { size: 4, type: "float32", stepMode: "dynamic", accessor: "getYears" },
    });
  }

  draw() {
    const { currentYear, growYears, tint, tintYears } = this.props;
    this.setShaderModuleProps({
      epoch: { year: currentYear, growYears: Math.max(growYears, 0.001), tintYears, tint: [...tint, 1] },
    });
  }
}
