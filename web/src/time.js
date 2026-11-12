import { LayerExtension } from "@deck.gl/core";

// Shows each object from its first year to its last. Buildings ("rise") grow out of the ground,
// carry a tint while they are new and sink in their last year; flat things ("fade") fade in.
// Buildings also get their walls drawn: rows of windows, a darker foot and a line under the roof.
// Tall buildings from the 1950s on get bands of glass in place of single windows.
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
      // epochWall: how far along the wall (0 to 1), the wall's length, the height above the foot
      // of this piece and the height of the piece, in metres as drawn. A roof has length -1.
      inject["vs:#decl"] += "out vec4 epochWall;\nout float epochFoot;\nout float epochCurtain;\n";
      inject["vs:#main-start"] += `
        float epochTall = elevations * max(epoch_grow, 0.02);
        epochFoot = vertexPositions.z;
        epochCurtain = step(1955.0, epochYears.x) * step(28.0, vertexPositions.z + elevations);
        #ifdef IS_SIDE_VERTEX
        vec2 epochSpan = (nextVertexPositions.xy - vertexPositions.xy)
          * project.commonUnitsPerWorldUnit.xy / project.commonUnitsPerMeter.xy;
        epochWall = vec4(positions.x, length(epochSpan), positions.y * epochTall, epochTall);
        #else
        epochWall = vec4(0.0, -1.0, epochTall, epochTall);
        #endif
      `;
      inject["fs:#decl"] = `in vec4 epochWall;
in float epochFoot;
in float epochCurtain;
const float EPOCH_FLOOR = 3.4;   // metres from floor to floor
// 1 between lo and hi, smoothed over the width of a pixel
float epoch_band(float x, float lo, float hi, float px) {
  return smoothstep(lo - px, lo + px, x) * (1.0 - smoothstep(hi - px, hi + px, x));
}
`;
      inject["fs:DECKGL_FILTER_COLOR"] = `
        if (epochWall.y >= 0.0) {
          float epochUp = epochFoot + epochWall.z;
          // darker towards the street, and a line under the roof
          float epochShade = mix(0.78, 1.0, smoothstep(0.0, 16.0, epochUp));
          float epochPx = fwidth(epochWall.z);
          epochShade *= 1.0 - 0.14 * (1.0 - smoothstep(0.5, 0.5 + epochPx, epochWall.w - epochWall.z))
            * (1.0 - smoothstep(0.3, 1.0, epochPx));
          // windows, as many as fit the wall; too far away to tell apart they blend into an even tone
          // A window every 3 m, or a pane of a glass wall every 1.5 m: x and y are the window's
          // sides within its bay, z how much of the bay is glass.
          float epochBay = mix(3.0, 1.5, epochCurtain);
          vec4 epochPane = mix(vec4(0.2, 0.8, 0.3, 0.82), vec4(0.06, 0.94, 0.26, 0.94), epochCurtain);
          vec2 epochCell = vec2(epochWall.x * max(1.0, floor(epochWall.y / epochBay + 0.5)), epochUp / EPOCH_FLOOR);
          vec2 epochSize = fwidth(epochCell);
          float epochGlass = epoch_band(fract(epochCell.x), epochPane.x, epochPane.y, epochSize.x)
            * epoch_band(fract(epochCell.y), epochPane.z, epochPane.w, epochSize.y);
          float epochNear = 1.0 - smoothstep(0.22, 0.5, max(epochSize.x, epochSize.y));
          float epochAll = (epochPane.y - epochPane.x) * (epochPane.w - epochPane.z);
          epochGlass = step(2.0, epochWall.y) * step(2.6, epochWall.w) * mix(epochAll, epochGlass, epochNear);
          // glass is darker than the wall and, on a glass wall, a little blue
          color.rgb *= epochShade * mix(vec3(1.0), mix(vec3(0.8), vec3(0.66, 0.74, 0.82), epochCurtain), epochGlass);
        }
      `;
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
