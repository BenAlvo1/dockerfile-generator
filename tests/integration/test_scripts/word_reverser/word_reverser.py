import sys

def reverse_words(input_text):
    """Reverse the order of words in the input text."""
    return ' '.join(reversed(input_text.split()))

if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python word_reverser.py '<input_text>'")
        sys.exit(1)

    input_text = sys.argv[1]
    output = reverse_words(input_text)
    print(output)
