/* Test fixture only. */
StringID GetSettingsValueString(int value, int min_val)
{
    return {this->str_val - min_val + value, value};
}
