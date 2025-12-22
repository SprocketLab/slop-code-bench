# TODO: Implement proper error handling


def process_data(items):
    """Process a list of items."""
    result = []
    for item in items:
        if item > 0:
            result.append(item * 2)
    return result


def main():
    data = [1, 2, 3, -1, 4, 5]
    processed = process_data(data)
    print(f"Processed: {processed}")


if __name__ == "__main__":
    main()
