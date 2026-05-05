using System.Windows;

namespace VRCOverlay.UI;

public partial class SettingsDialog : Window
{
    public string ApiUrl => TxtApiUrl.Text.TrimEnd('/');
    public string SettingsUrl { get; private set; }

    public SettingsDialog(string apiUrl, string settingsUrl)
    {
        InitializeComponent();
        TxtApiUrl.Text = apiUrl;
        SettingsUrl = settingsUrl;
    }

    private void BtnOk_Click(object sender, RoutedEventArgs e)
    {
        SettingsUrl = ApiUrl;
        DialogResult = true;
    }

    private void BtnCancel_Click(object sender, RoutedEventArgs e)
    {
        DialogResult = false;
    }
}
