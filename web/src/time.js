import { LayerExtension } from "@deck.gl/core";

// Shows each object from its year on. Buildings ("rise") grow out of the ground and carry a tint
// while they are new; flat things ("fade") fade in.
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
    getYear: { type: "accessor", value: 0 },
    currentYear: 2026,
    growYears: 1.5,
    // colour multiplier for a new object, back to 1 after tintYears
    tint: [1, 1, 1],
    tintYears: 1,
  };

  getShaders(extension) {
    const inject = {
      "vs:#decl": "in float epochYears;\nfloat epoch_age;\nfloat epoch_grow;\n",
      "vs:#main-start": `
        epoch_age = epoch.year - epochYears;
        epoch_grow = smoothstep(0.0, epoch.growYears, epoch_age);
      `,
      "vs:#main-end": "if (epoch_age < 0.0) gl_Position = vec4(0.0);\n",
    };
    if (extension.opts.mode === "rise") {
      inject["vs:DECKGL_FILTER_GL_POSITION"] = `
        vec4 epochPos = geometry.position;
        float epochBase = project_size(geometry.worldPosition.z);
        epochPos.z = epochBase + (epochPos.z - epochBase) * max(epoch_grow, 0.02);
        position = project_common_position_to_clipspace(epochPos);
      `;
      inject["vs:DECKGL_FILTER_COLOR"] = `
        color.rgb *= mix(epoch.tint.rgb, vec3(1.0), smoothstep(epoch.growYears, epoch.tintYears, epoch_age));
      `;
    } else {
      inject["vs:DECKGL_FILTER_COLOR"] = "color.a *= epoch_grow;\n";
    }
    return { modules: [epochModule], inject };
  }

  initializeState() {
    this.getAttributeManager()?.add({
      epochYears: { size: 1, type: "float32", stepMode: "dynamic", accessor: "getYear" },
    });
  }

  draw() {
    const { currentYear, growYears, tint, tintYears } = this.props;
    this.setShaderModuleProps({
      epoch: { year: currentYear, growYears: Math.max(growYears, 0.001), tintYears, tint: [...tint, 1] },
    });
  }
}
