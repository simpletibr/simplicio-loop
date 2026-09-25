import 'package:flutter_test/flutter_test.dart';

import 'package:starter_app/main.dart';

void main() {
  testWidgets('renders project name', (tester) async {
    await tester.pumpWidget(const StarterApp());

    expect(find.text('{project_name}'), findsOneWidget);
  });
}
