#version 330

// Segmented bar spectrum: each column is a stack of little lit blocks with a
// gap between them, like an LED meter. Colours come from the cava config, so
// the Color widget's theme (including the rainbow and trans gradients) drives
// this automatically.

in vec2 fragCoord;
out vec4 fragColor;

// bar values, left channel first (low to high), then right (high to low)
uniform float bars[512];

uniform int bars_count;     // number of bars (left + right)
uniform int bar_width;      // bar width, unused here
uniform int bar_spacing;    // space between bars

uniform vec3 u_resolution;  // window resolution

uniform vec3 bg_color;
uniform vec3 fg_color;

uniform int gradient_count;
uniform vec3 gradient_colors[8];

const float SEGMENTS = 26.0;    // blocks per column
const float LIT_SHARE = 0.70;   // how much of each block's slot is lit
const float UNLIT_LEVEL = 0.10; // faint ghost of the blocks above the level

// Colour for a given height, interpolated through the configured gradient.
vec3 colour_at(float y)
{
    if (gradient_count < 2)
    {
        return gradient_count == 1 ? gradient_colors[0] : fg_color;
    }
    float pos = clamp(y, 0.0, 1.0) * float(gradient_count - 1);
    int lower = int(floor(pos));
    int upper = min(lower + 1, gradient_count - 1);
    return mix(gradient_colors[lower], gradient_colors[upper], fract(pos));
}

void main()
{
    int bar = int(float(bars_count) * fragCoord.x);
    float bar_size = u_resolution.x / float(bars_count);
    float level = bars[bar];

    // gap between columns, honouring bar_spacing from the config
    float x_in_bar = mod(u_resolution.x * fragCoord.x, bar_size);
    float half_gap = max(float(bar_spacing), 1.0) * 0.5;
    bool column_gap = x_in_bar < half_gap || x_in_bar > bar_size - half_gap;

    // gap between the stacked blocks
    bool block_gap = fract(fragCoord.y * SEGMENTS) >= LIT_SHARE;

    if (column_gap || block_gap)
    {
        fragColor = vec4(bg_color, 1.0);
        return;
    }

    vec3 colour = colour_at(fragCoord.y);
    if (fragCoord.y < level)
    {
        fragColor = vec4(colour, 1.0);          // lit block
    }
    else
    {
        fragColor = vec4(mix(bg_color, colour, UNLIT_LEVEL), 1.0);   // unlit block
    }
}
