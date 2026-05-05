using System;
using System.Runtime.InteropServices;

namespace VRCOverlay.Win32;

/// <summary>
/// Embeds external windows into WPF using SetParent.
/// </summary>
public static class WindowEmbedder
{
    [DllImport("user32.dll")]
    private static extern IntPtr SetParent(IntPtr hWndChild, IntPtr hWndNewParent);

    [DllImport("user32.dll")]
    private static extern int SetWindowLong(IntPtr hWnd, int nIndex, int dwNewLong);

    [DllImport("user32.dll")]
    private static extern int GetWindowLong(IntPtr hWnd, int nIndex);

    [DllImport("user32.dll")]
    private static extern bool MoveWindow(IntPtr hWnd, int x, int y, int width, int height, bool repaint);

    private const int GWL_STYLE = -16;
    private const int WS_CAPTION = 0x00C00000;
    private const int WS_THICKFRAME = 0x00040000;
    private const int WS_SYSMENU = 0x00080000;

    public static void Embed(IntPtr childHwnd, IntPtr parentHwnd, int x, int y, int width, int height)
    {
        SetParent(childHwnd, parentHwnd);
        // Remove caption and thick frame
        int style = GetWindowLong(childHwnd, GWL_STYLE);
        style &= ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU);
        SetWindowLong(childHwnd, GWL_STYLE, style);
        MoveWindow(childHwnd, x, y, width, height, true);
    }

    public static void Resize(IntPtr childHwnd, int x, int y, int width, int height)
    {
        MoveWindow(childHwnd, x, y, width, height, true);
    }
}
