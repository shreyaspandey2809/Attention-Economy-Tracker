package com.attentiontracker.collector.ui.theme

import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color

val BackgroundDark = Color(0xFF1C2128)
val PanelDark = Color(0xFF252B33)
val PanelRaised = Color(0xFF2B323C)
val BorderSoft = Color(0xFF2E353F)
val TextPrimary = Color(0xFFE9EBEE)
val TextDim = Color(0xFF9AA3AF)
val TextFaint = Color(0xFF6B7480)
val Amber = Color(0xFFE8A33D)
val Sage = Color(0xFF7C9885)
val ErrorRed = Color(0xFFD97757)

private val AttentionColorScheme = darkColorScheme(
    background = BackgroundDark,
    surface = PanelDark,
    primary = Amber,
    onPrimary = BackgroundDark,
    secondary = Sage,
    error = ErrorRed,
    onBackground = TextPrimary,
    onSurface = TextPrimary
)

@Composable
fun AttentionCollectorTheme(content: @Composable () -> Unit) {
    MaterialTheme(
        colorScheme = AttentionColorScheme,
        content = content
    )
}
