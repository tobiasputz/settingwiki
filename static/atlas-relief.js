(() => {
  'use strict';

  /*
   * Seeker World Atlas 2.5D renderer.
   *
   * The atlas remains a normal map/image application. This renderer is a
   * progressive enhancement: a subdivided WebGL mesh is displaced by the
   * height map, then viewed through a constrained perspective camera. Existing
   * Seeker markers/regions/notes keep normalized UV coordinates and map.js asks
   * projectUV()/unprojectClient() to keep those DOM controls aligned with the
   * displaced surface. If anything fails the original 2D image remains intact.
   */

  const TERRAIN_VERTEX = `
    precision highp float;
    attribute vec2 a_uv;
    attribute float a_height;
    uniform float u_aspect;
    uniform float u_tilt;
    uniform float u_camera_distance;
    uniform float u_height_scale;
    uniform vec2 u_fit_center;
    uniform float u_fit_scale;
    varying vec2 v_uv;
    varying float v_height;
    varying float v_depth;

    void main() {
      float x = (a_uv.x - 0.5) * 2.0 * u_aspect;
      float y = (0.5 - a_uv.y) * 2.0;
      float z = a_height * u_height_scale;
      float ct = cos(u_tilt);
      float st = sin(u_tilt);

      // Constrained camera: north/top is farther away and high terrain moves
      // toward the camera. This creates the Runeterra-like miniature relief
      // without allowing a free-flying game-engine camera.
      float viewY = y * ct + z * st;
      float depth = max(0.35, u_camera_distance + y * st - z * ct);
      float w = depth / u_camera_distance;
      vec2 raw = vec2((x / u_aspect) / w, viewY / w);
      vec2 ndc = (raw - u_fit_center) * u_fit_scale;

      // Put the perspective denominator in clip-space w so texture
      // interpolation remains perspective-correct across each triangle.
      gl_Position = vec4(ndc * w, 0.0, w);
      v_uv = a_uv;
      v_height = a_height;
      v_depth = depth;
    }
  `;

  const TERRAIN_FRAGMENT = `
    precision mediump float;
    varying vec2 v_uv;
    varying float v_height;
    varying float v_depth;
    uniform sampler2D u_albedo;
    uniform sampler2D u_normal;
    uniform sampler2D u_water;
    uniform sampler2D u_cloud;
    uniform sampler2D u_label;
    uniform sampler2D u_ao;
    uniform vec2 u_texel;
    uniform vec2 u_grid_density;
    uniform float u_zoom;
    uniform float u_time;
    uniform float u_strength;
    uniform float u_label_declutter;
    uniform float u_label_start;
    uniform float u_label_end;
    uniform float u_grid;

    vec3 mapColor(vec2 uv) {
      return texture2D(u_albedo, clamp(uv, vec2(0.0), vec2(1.0))).rgb;
    }

    float expandedLabel(vec2 uv) {
      float m = texture2D(u_label, uv).r;
      vec2 d = u_texel * 3.5;
      m = max(m, texture2D(u_label, uv + vec2( d.x, 0.0)).r);
      m = max(m, texture2D(u_label, uv + vec2(-d.x, 0.0)).r);
      m = max(m, texture2D(u_label, uv + vec2(0.0,  d.y)).r);
      m = max(m, texture2D(u_label, uv + vec2(0.0, -d.y)).r);
      m = max(m, texture2D(u_label, uv + d).r);
      m = max(m, texture2D(u_label, uv - d).r);
      return smoothstep(0.05, 0.52, m);
    }

    vec3 localBackground(vec2 uv) {
      vec2 a = u_texel * 8.0;
      vec2 b = u_texel * 16.0;
      vec2 c = u_texel * 25.0;
      vec3 outColor = mapColor(uv + vec2( a.x, 0.0)) + mapColor(uv - vec2(a.x, 0.0));
      outColor += mapColor(uv + vec2(0.0, a.y)) + mapColor(uv - vec2(0.0, a.y));
      outColor += mapColor(uv + vec2( b.x, b.y)) + mapColor(uv + vec2(-b.x, b.y));
      outColor += mapColor(uv + vec2( b.x,-b.y)) + mapColor(uv + vec2(-b.x,-b.y));
      outColor += mapColor(uv + vec2( c.x, 0.0)) + mapColor(uv - vec2(c.x, 0.0));
      outColor += mapColor(uv + vec2(0.0, c.y)) + mapColor(uv - vec2(0.0, c.y));
      return outColor * 0.0833333333;
    }

    float atlasGrid(vec2 uv) {
      vec2 cell = fract(uv * u_grid_density);
      vec2 edge = min(cell, 1.0 - cell);
      float line = 1.0 - smoothstep(0.0, 0.018, min(edge.x, edge.y));
      return line * u_grid;
    }

    void main() {
      vec2 uv = v_uv;
      vec3 original = mapColor(uv);
      vec3 color = original;
      float water = texture2D(u_water, uv).r;
      float cloud = texture2D(u_cloud, uv).r;
      float ao = texture2D(u_ao, uv).r;
      vec3 normal = normalize(texture2D(u_normal, uv).rgb * 2.0 - 1.0);

      // Relief lighting is deliberately suppressed by both masks. Water stays
      // level and atmospheric cloud paint does not acquire mountain lighting.
      vec3 lightDir = normalize(vec3(-0.48, 0.62, 0.82));
      float diffuse = clamp(dot(normal, lightDir), 0.0, 1.0);
      float reliefMask = (1.0 - water) * (1.0 - cloud) * u_strength;
      float reliefShade = 0.76 + diffuse * 0.40;
      reliefShade *= mix(1.0, mix(0.86, 1.0, ao), 0.62);
      color *= mix(1.0, reliefShade, clamp(reliefMask, 0.0, 1.35));

      // Atmospheric perspective: only a whisper of haze toward the far/north
      // edge. It reinforces depth without recoloring the cartography.
      float distanceHaze = clamp((v_depth - 4.0) * 0.16, 0.0, 0.12);
      color = mix(color, vec3(0.67, 0.74, 0.78), distanceHaze * (1.0 - cloud));

      // Restrained sea shimmer. It never displaces the ocean surface.
      float wave = sin((uv.x * 92.0 + uv.y * 47.0) + u_time * 0.42) * 0.5 + 0.5;
      float wave2 = sin((uv.x * 37.0 - uv.y * 73.0) - u_time * 0.31) * 0.5 + 0.5;
      color += vec3(0.025, 0.045, 0.055) * (wave * wave2) * water * 0.28;

      // Major painted titles remain useful at world view but become huge when
      // zoomed in. Fade only the authored mask, never settlement labels.
      float labelFade = smoothstep(u_label_start, u_label_end, u_zoom) * u_label_declutter;
      float label = expandedLabel(uv) * labelFade;
      if (label > 0.001) {
        color = mix(color, localBackground(uv), clamp(label * 0.96, 0.0, 0.96));
      }

      float grid = atlasGrid(uv);
      color = mix(color, vec3(0.80, 0.71, 0.53), grid * 0.12 * (1.0 - cloud));

      // Crucially, cloud pixels return toward their source luminance instead of
      // inheriting AO/normal shading from the terrain below. Snow/ice are NOT in
      // this mask, so genuine pale terrain still receives relief.
      color = mix(color, original, cloud * 0.92);
      gl_FragColor = vec4(color, 1.0);
    }
  `;

  const OVERLAY_FRAGMENT = `
    precision mediump float;
    varying vec2 v_uv;
    uniform sampler2D u_overlay;
    uniform float u_opacity;
    void main() {
      vec4 c = texture2D(u_overlay, v_uv);
      if (c.a * u_opacity < 0.004) discard;
      gl_FragColor = vec4(c.rgb, c.a * u_opacity);
    }
  `;

  const loadImage = src => new Promise((resolve, reject) => {
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Could not load atlas texture: ${src}`));
    img.src = src;
  });

  function shader(gl, type, source) {
    const sh = gl.createShader(type);
    gl.shaderSource(sh, source);
    gl.compileShader(sh);
    if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
      const message = gl.getShaderInfoLog(sh) || 'Shader compile failed';
      gl.deleteShader(sh);
      throw new Error(message);
    }
    return sh;
  }

  function program(gl, vertexSource, fragmentSource) {
    const p = gl.createProgram();
    gl.attachShader(p, shader(gl, gl.VERTEX_SHADER, vertexSource));
    gl.attachShader(p, shader(gl, gl.FRAGMENT_SHADER, fragmentSource));
    gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) {
      const message = gl.getProgramInfoLog(p) || 'Shader link failed';
      gl.deleteProgram(p);
      throw new Error(message);
    }
    return p;
  }

  function makeTexture(gl, image, unit = 0) {
    const t = gl.createTexture();
    gl.activeTexture(gl.TEXTURE0 + unit);
    gl.bindTexture(gl.TEXTURE_2D, t);
    gl.pixelStorei(gl.UNPACK_FLIP_Y_WEBGL, true);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_S, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_WRAP_T, gl.CLAMP_TO_EDGE);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MIN_FILTER, gl.LINEAR);
    gl.texParameteri(gl.TEXTURE_2D, gl.TEXTURE_MAG_FILTER, gl.LINEAR);
    gl.texImage2D(gl.TEXTURE_2D, 0, gl.RGBA, gl.RGBA, gl.UNSIGNED_BYTE, image);
    return t;
  }

  function pixelPlane(image) {
    const c = document.createElement('canvas');
    c.width = image.naturalWidth;
    c.height = image.naturalHeight;
    const ctx = c.getContext('2d', {willReadFrequently: true});
    ctx.drawImage(image, 0, 0);
    const rgba = ctx.getImageData(0, 0, c.width, c.height).data;
    const values = new Float32Array(c.width * c.height);
    for (let i = 0, p = 0; p < values.length; i += 4, p += 1) values[p] = rgba[i] / 255;
    return {width: c.width, height: c.height, values};
  }

  function bilinear(plane, u, v) {
    if (!plane) return 0;
    const x = Math.max(0, Math.min(plane.width - 1, u * (plane.width - 1)));
    const y = Math.max(0, Math.min(plane.height - 1, v * (plane.height - 1)));
    const x0 = Math.floor(x), y0 = Math.floor(y);
    const x1 = Math.min(plane.width - 1, x0 + 1), y1 = Math.min(plane.height - 1, y0 + 1);
    const fx = x - x0, fy = y - y0;
    const a = plane.values[y0 * plane.width + x0];
    const b = plane.values[y0 * plane.width + x1];
    const c = plane.values[y1 * plane.width + x0];
    const d = plane.values[y1 * plane.width + x1];
    return (a * (1 - fx) + b * fx) * (1 - fy) + (c * (1 - fx) + d * fx) * fy;
  }

  class AtlasRelief {
    constructor({canvas, image, root, profile, effects}) {
      this.canvas = canvas;
      this.image = image;
      this.root = root;
      this.profile = profile || {};
      this.effects = effects || {};
      this.zoom = 1;
      this.enabled = true;
      this.ready = false;
      this.raf = 0;
      this.lastFrame = 0;
      this.overlayTextures = [];
      this.reducedMotion = window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches || false;
      this.aspect = Number(this.profile.aspect || 1);
      this.tilt = Number(this.profile.tiltDegrees ?? 28) * Math.PI / 180;
      this.cameraDistance = Number(this.profile.cameraDistance ?? 4.2);
      this.elevationScaleBase = Number(this.profile.elevationScale ?? 0.22);
      this.fitMargin = Math.max(0.75, Math.min(0.98, Number(this.profile.fitMargin ?? 0.925)));
      this.fitCenter = {x: 0, y: 0};
      this.fitScale = 1;
    }

    terrainStrength() {
      return Math.max(0, Math.min(1.5, Number(this.effects.terrain_strength ?? this.profile.terrainStrength ?? 1)));
    }

    heightScale() {
      return this.elevationScaleBase * this.terrainStrength();
    }

    cloudSuppression() {
      return Math.max(0, Math.min(1, Number(this.profile.cloudReliefSuppression ?? 0.92)));
    }

    effectiveHeight(u, v) {
      const h = bilinear(this.heightPlane, u, v);
      const cloud = bilinear(this.cloudPlane, u, v);
      return h * (1 - cloud * this.cloudSuppression());
    }

    rawProject(u, v, height = this.effectiveHeight(u, v)) {
      const x = (u - 0.5) * 2 * this.aspect;
      const y = (0.5 - v) * 2;
      const z = height * this.heightScale();
      const ct = Math.cos(this.tilt), st = Math.sin(this.tilt);
      const viewY = y * ct + z * st;
      const depth = Math.max(0.35, this.cameraDistance + y * st - z * ct);
      const p = this.cameraDistance / depth;
      return {x: (x * p) / this.aspect, y: viewY * p, depth};
    }

    projectUV(u, v) {
      if (!this.ready) return {x: u * (this.canvas?.width || 1), y: v * (this.canvas?.height || 1), u, v};
      const p = this.rawProject(Number(u), Number(v));
      const nx = (p.x - this.fitCenter.x) * this.fitScale;
      const ny = (p.y - this.fitCenter.y) * this.fitScale;
      return {
        x: (nx * 0.5 + 0.5) * this.canvas.width,
        y: (0.5 - ny * 0.5) * this.canvas.height,
        u: Number(u), v: Number(v), depth: p.depth,
      };
    }

    unprojectCanvas(px, py) {
      if (!this.ready || !this.canvas.width || !this.canvas.height) return null;
      const tx = (px / this.canvas.width) * 2 - 1;
      const ty = 1 - (py / this.canvas.height) * 2;
      const targetX = tx / this.fitScale + this.fitCenter.x;
      const targetY = ty / this.fitScale + this.fitCenter.y;

      // Start with the corresponding flat-map coordinate and solve the displaced
      // projection with a tiny numerical Jacobian. Six iterations is comfortably
      // sub-pixel for normal atlas terrain while remaining cheap for note placing.
      let u = Math.max(0, Math.min(1, px / this.canvas.width));
      let v = Math.max(0, Math.min(1, py / this.canvas.height));
      const eps = 0.0007;
      for (let i = 0; i < 7; i += 1) {
        const p = this.rawProject(u, v);
        const ex = p.x - targetX, ey = p.y - targetY;
        if (Math.abs(ex) + Math.abs(ey) < 0.00002) break;
        const pu = this.rawProject(Math.min(1, u + eps), v);
        const pv = this.rawProject(u, Math.min(1, v + eps));
        const ax = (pu.x - p.x) / eps, ay = (pu.y - p.y) / eps;
        const bx = (pv.x - p.x) / eps, by = (pv.y - p.y) / eps;
        const det = ax * by - ay * bx;
        if (Math.abs(det) < 1e-8) break;
        const du = ( ex * by - ey * bx) / det;
        const dv = (-ex * ay + ey * ax) / det;
        u = Math.max(0, Math.min(1, u - du));
        v = Math.max(0, Math.min(1, v - dv));
      }
      return {u, v};
    }

    unprojectClient(clientX, clientY) {
      const r = this.canvas.getBoundingClientRect();
      if (!r.width || !r.height) return null;
      const px = (clientX - r.left) / r.width * this.canvas.width;
      const py = (clientY - r.top) / r.height * this.canvas.height;
      return this.unprojectCanvas(px, py);
    }

    recomputeFit() {
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      const uv = this.meshUV, heights = this.meshHeight;
      for (let i = 0; i < heights.length; i += 1) {
        const p = this.rawProject(uv[i * 2], uv[i * 2 + 1], heights[i]);
        minX = Math.min(minX, p.x); maxX = Math.max(maxX, p.x);
        minY = Math.min(minY, p.y); maxY = Math.max(maxY, p.y);
      }
      this.fitCenter = {x: (minX + maxX) * 0.5, y: (minY + maxY) * 0.5};
      const half = Math.max((maxX - minX) * 0.5, (maxY - minY) * 0.5, 0.001);
      this.fitScale = this.fitMargin / half;
    }

    buildMesh() {
      const maxX = Math.max(48, Math.min(220, Number(this.profile.meshSegmentsX ?? 184) | 0));
      const maxY = Math.max(34, Math.min(180, Number(this.profile.meshSegmentsY ?? Math.round(maxX / this.aspect)) | 0));
      const verts = (maxX + 1) * (maxY + 1);
      if (verts >= 65535) throw new Error('Atlas terrain mesh is too dense for WebGL1 indices.');
      const uv = new Float32Array(verts * 2);
      const heights = new Float32Array(verts);
      let p = 0;
      for (let y = 0; y <= maxY; y += 1) {
        const v = y / maxY;
        for (let x = 0; x <= maxX; x += 1) {
          const u = x / maxX;
          uv[p * 2] = u; uv[p * 2 + 1] = v;
          heights[p] = this.effectiveHeight(u, v);
          p += 1;
        }
      }
      const indices = new Uint16Array(maxX * maxY * 6);
      let q = 0;
      for (let y = 0; y < maxY; y += 1) {
        for (let x = 0; x < maxX; x += 1) {
          const a = y * (maxX + 1) + x;
          const b = a + 1;
          const c = a + (maxX + 1);
          const d = c + 1;
          indices[q++] = a; indices[q++] = c; indices[q++] = b;
          indices[q++] = b; indices[q++] = c; indices[q++] = d;
        }
      }
      this.meshUV = uv;
      this.meshHeight = heights;
      this.meshIndices = indices;
      this.indexCount = indices.length;
      this.recomputeFit();
    }

    uploadGeometry() {
      const gl = this.gl;
      this.uvBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.uvBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, this.meshUV, gl.STATIC_DRAW);
      this.heightBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ARRAY_BUFFER, this.heightBuffer);
      gl.bufferData(gl.ARRAY_BUFFER, this.meshHeight, gl.STATIC_DRAW);
      this.indexBuffer = gl.createBuffer();
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
      gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, this.meshIndices, gl.STATIC_DRAW);
    }

    bindGeometry(p) {
      const gl = this.gl;
      const uvLoc = gl.getAttribLocation(p, 'a_uv');
      const hLoc = gl.getAttribLocation(p, 'a_height');
      gl.bindBuffer(gl.ARRAY_BUFFER, this.uvBuffer);
      gl.enableVertexAttribArray(uvLoc);
      gl.vertexAttribPointer(uvLoc, 2, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ARRAY_BUFFER, this.heightBuffer);
      gl.enableVertexAttribArray(hLoc);
      gl.vertexAttribPointer(hLoc, 1, gl.FLOAT, false, 0, 0);
      gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, this.indexBuffer);
    }

    setVertexUniforms(p) {
      const gl = this.gl;
      gl.uniform1f(gl.getUniformLocation(p, 'u_aspect'), this.aspect);
      gl.uniform1f(gl.getUniformLocation(p, 'u_tilt'), this.tilt);
      gl.uniform1f(gl.getUniformLocation(p, 'u_camera_distance'), this.cameraDistance);
      gl.uniform1f(gl.getUniformLocation(p, 'u_height_scale'), this.heightScale());
      gl.uniform2f(gl.getUniformLocation(p, 'u_fit_center'), this.fitCenter.x, this.fitCenter.y);
      gl.uniform1f(gl.getUniformLocation(p, 'u_fit_scale'), this.fitScale);
    }

    async loadOverlayTextures() {
      const gl = this.gl;
      const rows = [...this.root.querySelectorAll('.atlas-overlay-layer')];
      this.overlayTextures = [];
      for (const element of rows) {
        try {
          const img = element.complete && element.naturalWidth ? element : await loadImage(element.currentSrc || element.src);
          this.overlayTextures.push({
            element,
            texture: makeTexture(gl, img, 0),
          });
        } catch (err) {
          console.warn('[Seeker Atlas] Overlay layer skipped in 3D mode:', err);
        }
      }
    }

    async init() {
      if (!this.canvas || !this.image || !this.profile?.heightMap || !this.profile?.normalMap) return false;
      const gl = this.canvas.getContext('webgl', {
        alpha: true,
        antialias: true,
        depth: true,
        powerPreference: 'high-performance',
      });
      if (!gl) return false;
      this.gl = gl;
      this.terrainProgram = program(gl, TERRAIN_VERTEX, TERRAIN_FRAGMENT);
      this.overlayProgram = program(gl, TERRAIN_VERTEX, OVERLAY_FRAGMENT);

      const albedoSrc = this.profile.albedoMap || this.image.currentSrc || this.image.src;
      const [albedo, height, normal, water, cloud, label, ao] = await Promise.all([
        loadImage(albedoSrc),
        loadImage(this.profile.heightMap),
        loadImage(this.profile.normalMap),
        loadImage(this.profile.waterMask),
        loadImage(this.profile.cloudMask),
        loadImage(this.profile.labelMask),
        loadImage(this.profile.aoMap),
      ]);

      const expectedWidth = Number(this.profile.width || 0);
      const expectedHeight = Number(this.profile.height || 0);
      const fallbackWidth = this.image.naturalWidth;
      const fallbackHeight = this.image.naturalHeight;
      if ((expectedWidth && fallbackWidth !== expectedWidth) || (expectedHeight && fallbackHeight !== expectedHeight)) {
        throw new Error(
          `Atlas terrain profile expects ${expectedWidth || '?'}×${expectedHeight || '?'} but the map is ` +
          `${fallbackWidth}×${fallbackHeight}. Falling back to the original 2D map.`
        );
      }
      const required = [['albedo', albedo], ['height', height], ['normal', normal], ['water', water], ['cloud', cloud], ['label', label], ['ao', ao]];
      for (const [kind, asset] of required) {
        if (asset.naturalWidth !== fallbackWidth || asset.naturalHeight !== fallbackHeight) {
          throw new Error(`Atlas ${kind} texture dimensions do not match the map. Falling back to 2D.`);
        }
      }

      const maxTex = gl.getParameter(gl.MAX_TEXTURE_SIZE) || 2048;
      if (fallbackWidth > maxTex || fallbackHeight > maxTex) {
        throw new Error(`Map texture ${fallbackWidth}×${fallbackHeight} exceeds this GPU's ${maxTex}px texture limit.`);
      }

      this.canvas.width = fallbackWidth;
      this.canvas.height = fallbackHeight;
      this.canvas.style.width = `${fallbackWidth}px`;
      this.canvas.style.height = `${fallbackHeight}px`;
      this.aspect = fallbackWidth / fallbackHeight;
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);

      this.heightPlane = pixelPlane(height);
      this.cloudPlane = pixelPlane(cloud);
      this.buildMesh();
      this.uploadGeometry();

      this.terrainTextures = [albedo, normal, water, cloud, label, ao].map((img, unit) => makeTexture(gl, img, unit));
      const p = this.terrainProgram;
      gl.useProgram(p);
      ['u_albedo', 'u_normal', 'u_water', 'u_cloud', 'u_label', 'u_ao'].forEach((name, unit) => {
        gl.uniform1i(gl.getUniformLocation(p, name), unit);
      });
      gl.uniform2f(gl.getUniformLocation(p, 'u_texel'), 1 / this.canvas.width, 1 / this.canvas.height);
      gl.uniform2f(gl.getUniformLocation(p, 'u_grid_density'), this.canvas.width / 120, this.canvas.height / 120);
      gl.uniform1f(gl.getUniformLocation(p, 'u_label_start'), Number(this.profile.labelFadeStart ?? 1.22));
      gl.uniform1f(gl.getUniformLocation(p, 'u_label_end'), Number(this.profile.labelFadeEnd ?? 1.95));

      await this.loadOverlayTextures();

      this.ready = true;
      this.root.classList.add('atlas-relief-ready');
      this.draw(performance.now());
      if (!this.reducedMotion) this.start();
      this.canvas.addEventListener('webglcontextlost', e => {
        e.preventDefault();
        this.ready = false;
        this.root.classList.remove('atlas-relief-ready');
        this.root.classList.add('atlas-relief-failed');
      }, {once: true});
      return true;
    }

    setEnabled(value) {
      this.enabled = !!value;
      this.root.classList.toggle('atlas-relief-enabled', this.enabled);
      if (this.enabled && this.ready) this.draw(performance.now());
    }

    setZoom(value) {
      this.zoom = Math.max(0.1, Number(value) || 1);
      if (this.enabled && this.ready) this.draw(performance.now());
    }

    setEffects(effects) {
      const oldStrength = this.terrainStrength();
      this.effects = effects || this.effects || {};
      if (Math.abs(oldStrength - this.terrainStrength()) > 0.0001 && this.ready) this.recomputeFit();
      if (this.enabled && this.ready) this.draw(performance.now());
    }

    drawTerrain(now) {
      const gl = this.gl, p = this.terrainProgram;
      gl.useProgram(p);
      this.bindGeometry(p);
      this.setVertexUniforms(p);
      gl.uniform1f(gl.getUniformLocation(p, 'u_zoom'), this.zoom);
      gl.uniform1f(gl.getUniformLocation(p, 'u_time'), now / 1000);
      gl.uniform1f(gl.getUniformLocation(p, 'u_strength'), this.terrainStrength());
      gl.uniform1f(gl.getUniformLocation(p, 'u_label_declutter'), this.effects.label_declutter === false ? 0 : 1);
      gl.uniform1f(gl.getUniformLocation(p, 'u_grid'), this.effects.grid ? 1 : 0);
      this.terrainTextures.forEach((t, unit) => {
        gl.activeTexture(gl.TEXTURE0 + unit);
        gl.bindTexture(gl.TEXTURE_2D, t);
      });
      gl.drawElements(gl.TRIANGLES, this.indexCount, gl.UNSIGNED_SHORT, 0);
    }

    drawOverlays() {
      if (!this.overlayTextures.length) return;
      const gl = this.gl, p = this.overlayProgram;
      gl.useProgram(p);
      this.bindGeometry(p);
      this.setVertexUniforms(p);
      gl.uniform1i(gl.getUniformLocation(p, 'u_overlay'), 0);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
      for (const row of this.overlayTextures) {
        const el = row.element;
        if (el.hidden || getComputedStyle(el).display === 'none') continue;
        const opacity = Math.max(0, Math.min(1, Number(el.style.opacity || 1)));
        gl.uniform1f(gl.getUniformLocation(p, 'u_opacity'), opacity);
        gl.activeTexture(gl.TEXTURE0);
        gl.bindTexture(gl.TEXTURE_2D, row.texture);
        gl.drawElements(gl.TRIANGLES, this.indexCount, gl.UNSIGNED_SHORT, 0);
      }
      gl.disable(gl.BLEND);
    }

    draw(now = performance.now()) {
      if (!this.ready || !this.enabled || !this.gl) return;
      const gl = this.gl;
      gl.viewport(0, 0, this.canvas.width, this.canvas.height);
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT | gl.DEPTH_BUFFER_BIT);
      gl.disable(gl.CULL_FACE);
      gl.disable(gl.DEPTH_TEST);
      this.drawTerrain(now);
      this.drawOverlays();
    }

    start() {
      if (this.raf || this.reducedMotion) return;
      const tick = now => {
        this.raf = requestAnimationFrame(tick);
        if (!this.enabled || !this.ready || document.hidden || now - this.lastFrame < 50) return; // ~20fps
        this.lastFrame = now;
        this.draw(now);
      };
      this.raf = requestAnimationFrame(tick);
    }

    destroy() {
      cancelAnimationFrame(this.raf);
      this.raf = 0;
    }
  }

  window.SeekerAtlasRelief = {
    async create(options) {
      const renderer = new AtlasRelief(options);
      try {
        const ok = await renderer.init();
        return ok ? renderer : null;
      } catch (err) {
        console.warn('[Seeker Atlas] 2.5D terrain disabled:', err);
        options?.root?.classList?.add('atlas-relief-failed');
        return null;
      }
    }
  };
})();
