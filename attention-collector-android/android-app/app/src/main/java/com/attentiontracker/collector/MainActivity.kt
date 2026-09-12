package com.attentiontracker.collector

import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.compose.setContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.material3.Surface
import androidx.compose.ui.Modifier
import com.attentiontracker.collector.ui.CollectorScreen
import com.attentiontracker.collector.ui.theme.AttentionCollectorTheme
import com.attentiontracker.collector.ui.theme.BackgroundDark

class MainActivity : ComponentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            AttentionCollectorTheme {
                Surface(
                    modifier = Modifier.fillMaxSize().background(BackgroundDark)
                ) {
                    CollectorScreen()
                }
            }
        }
    }
}
